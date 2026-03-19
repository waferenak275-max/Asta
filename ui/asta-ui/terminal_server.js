import { WebSocketServer } from 'ws';
import { spawn, execSync } from 'child_process';
import os from 'os';
import path from 'path';
import { fileURLToPath } from 'url';
import fs from 'fs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Priority: Argument > Env > PORTABLE_EXECUTABLE_DIR > Default (Dev relative)
const ROOT_DIR = process.argv[2] 
  || process.env.ROOT_DIR 
  || process.env.PORTABLE_EXECUTABLE_DIR 
  || path.resolve(__dirname, '../../');

const wss = new WebSocketServer({ port: 8001 });
console.log(`[Terminal Server] Root set to: ${ROOT_DIR}`);

let backendProc = null;
let lastTotalTime = 0;
let lastIdleTime = 0;

function getCpuUsage() {
    const cpus = os.cpus();
    let totalTime = 0, idleTime = 0;
    cpus.forEach(cpu => {
        for (let type in cpu.times) totalTime += cpu.times[type];
        idleTime += cpu.times.idle;
    });
    const deltaTotal = totalTime - lastTotalTime;
    const deltaIdle = idleTime - lastIdleTime;
    lastTotalTime = totalTime; lastIdleTime = idleTime;
    return deltaTotal === 0 ? "0.0" : ((1 - deltaIdle / deltaTotal) * 100).toFixed(1);
}

function getDiskUsage() {
    return new Promise((resolve) => {
        const cmd = spawn('wmic', ['logicaldisk', 'where', 'DeviceID="C:"', 'get', 'FreeSpace,Size', '/format:list'], { shell: true });
        let out = '';
        cmd.stdout.on('data', (d) => out += d.toString());
        cmd.on('close', () => {
            const lines = out.split(/\r?\n/);
            let free = 0, size = 1;
            lines.forEach(l => {
                const parts = l.trim().split('=');
                if (parts[0] === 'FreeSpace') free = parseInt(parts[1]);
                if (parts[0] === 'Size') size = parseInt(parts[1]);
            });
            resolve(((size - free) / size * 100).toFixed(1));
        });
        cmd.on('error', () => resolve("0.0"));
    });
}

wss.on('connection', (ws) => {
    ws.send(JSON.stringify({ type: 'output', data: `[Asta] Terminal connected.\n[Asta] Root: ${ROOT_DIR}\n` }));

    const shell = spawn('cmd.exe', [], { cwd: ROOT_DIR, env: process.env, shell: true });
    shell.stdout.on('data', (data) => ws.send(JSON.stringify({ type: 'output', data: data.toString() })));
    shell.stderr.on('data', (data) => ws.send(JSON.stringify({ type: 'output', data: data.toString() })));

    const statsInterval = setInterval(async () => {
        if (ws.readyState !== 1) return;
        ws.send(JSON.stringify({ type: 'stats', data: { cpu: getCpuUsage(), ram: (((os.totalmem()-os.freemem())/os.totalmem())*100).toFixed(1), disk: await getDiskUsage() } }));
    }, 2000);

    ws.on('message', (message) => {
        const input = message.toString().trim();
        const cmd = input.toLowerCase();

        if (cmd === 'cls' || cmd === 'clear') {
            ws.send(JSON.stringify({ type: 'clear' }));
            shell.stdin.write('\n');
            return;
        }

        if (cmd === 'install') {
            ws.send(JSON.stringify({ type: 'output', data: "\n[Asta Setup] Memulai proses instalasi...\n" }));
            
            // 1. Create venv
            ws.send(JSON.stringify({ type: 'output', data: "1. Membuat Virtual Environment (venv) dengan Python 3.11...\n" }));
            try {
                // Mencoba py -3.11 atau python
                shell.stdin.write('py -3.11 -m venv venv || python -m venv venv\n');
            } catch (e) {
                ws.send(JSON.stringify({ type: 'output', data: "[Error] Pastikan Python 3.11 sudah terinstal di sistem.\n" }));
                return;
            }

            // 2. Install Dependencies
            const deps = "llama-cpp-python uvicorn fastapi websockets numpy transformers torch sentencepiece accelerate sentence-transformers tavily-python duckduckgo-search huggingface_hub";
            ws.send(JSON.stringify({ type: 'output', data: `2. Menginstal dependensi: ${deps.slice(0, 50)}...\n` }));
            shell.stdin.write(`venv\\Scripts\\pip install ${deps}\n`);

            // 3. Download Models
            ws.send(JSON.stringify({ type: 'output', data: "3. Mengunduh Model & Tokenizer (HuggingFace)...\n" }));
            
            // Model Paths
            const modelDir = path.join(ROOT_DIR, 'model');
            const sailorDir = path.join(modelDir, 'Sailor2-8B');
            const qwenDir = path.join(modelDir, 'Qwen2.5-3B');
            const embDir = path.join(modelDir, 'embedding_model', 'paraphrase-multilingual-MiniLM-L12-v2');

            // Script download via huggingface-cli
            const downloadScript = `
mkdir "${sailorDir}" 2>nul
mkdir "${qwenDir}" 2>nul
mkdir "${modelDir}\\embedding_model" 2>nul

echo [Asta] Mengunduh Sailor2 8B...
venv\\Scripts\\huggingface-cli download sailor-ai/Sailor2-8B-Chat-GGUF Sailor2-8B-Chat-Q4_K_M.gguf --local-dir "${sailorDir}" --local-dir-use-symlinks False
venv\\Scripts\\huggingface-cli download sailor-ai/Sailor2-8B-Chat --local-dir "${sailorDir}\\tokenizer" --local-dir-use-symlinks False

echo [Asta] Mengunduh Qwen 2.5 3B...
venv\\Scripts\\huggingface-cli download Qwen/Qwen2.5-3B-Instruct-GGUF qwen2.5-3b-instruct-q4_k_m.gguf --local-dir "${qwenDir}" --local-dir-use-symlinks False
venv\\Scripts\\huggingface-cli download Qwen/Qwen2.5-3B-Instruct --local-dir "${qwenDir}\\tokenizer" --local-dir-use-symlinks False

echo [Asta] Mengunduh Embedding Model...
venv\\Scripts\\python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2').save('${embDir}')"

echo [Asta] Setup selesai! Silakan masukkan folder LoRA Anda secara manual ke folder 'model/LoRA-all-adapter/'.
`.trim();

            shell.stdin.write(downloadScript + '\n');
            return;
        }

        if (cmd === 'start backend') {
            if (backendProc) {
                ws.send(JSON.stringify({ type: 'output', data: "[Terminal] Backend is already running.\n" }));
                return;
            }
            const pythonPath = path.join(ROOT_DIR, 'venv', 'Scripts', 'python.exe');
            if (!fs.existsSync(pythonPath)) {
                ws.send(JSON.stringify({ type: 'output', data: `[Error] Venv tidak ditemukan. Jalankan 'install' dulu.\n` }));
                return;
            }
            ws.send(JSON.stringify({ type: 'output', data: "[Terminal] Starting Backend...\n" }));
            backendProc = spawn(pythonPath, ['-m', 'uvicorn', 'api:app', '--host', '0.0.0.0', '--port', '8000'], { cwd: ROOT_DIR, shell: true });
            backendProc.stdout.on('data', (d) => ws.send(JSON.stringify({ type: 'output', data: `[BACKEND] ${d}` })));
            backendProc.stderr.on('data', (d) => ws.send(JSON.stringify({ type: 'output', data: `[BACKEND] ${d}` })));
            backendProc.on('close', () => {
                ws.send(JSON.stringify({ type: 'output', data: "[Terminal] Backend process closed.\n" }));
                backendProc = null;
            });
            return;
        }

        if (cmd === 'stop backend') {
            if (backendProc) {
                // Di sini kita tidak bisa pakai tree-kill langsung (karena library node), tapi bisa panggil taskkill
                spawn("taskkill", ["/pid", backendProc.pid, "/f", "/t"]);
                backendProc = null;
                ws.send(JSON.stringify({ type: 'output', data: "[Terminal] Backend stopped.\n" }));
            } else {
                ws.send(JSON.stringify({ type: 'output', data: "[Terminal] Backend is not running.\n" }));
            }
            return;
        }

        if (cmd === 'help') {
            ws.send(JSON.stringify({ type: 'output', data: "\nCommands:\n  install       - Auto setup venv, depedensi, dan download model\n  start backend - Menjalankan server python\n  stop backend  - Menghentikan server python\n  cls           - Bersihkan layar\n  dir           - Lihat isi folder\n" }));
            return;
        }

        shell.stdin.write(input + '\n');
    });

    ws.on('close', () => {
        clearInterval(statsInterval);
        shell.kill();
    });
});
