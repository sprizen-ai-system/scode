#!/usr/bin/env python3
"""
scode v2 - Your terminal. Evolved. Supercharged.
Multi-provider | File Editing | Rich TUI | Tool Use | Self-Healing | Immortal
"""

import os, sys, json, time, subprocess, threading, traceback, re, shutil, difflib
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

# ─── BOOTSTRAP: auto-install deps ────────────────────────────────────────────
def bootstrap():
    required = {"rich": "rich", "prompt_toolkit": "prompt-toolkit"}
    missing = []
    for mod, pkg in required.items():
        try: __import__(mod)
        except ImportError: missing.append(pkg)
    if missing:
        print(f"[scode] Installing dependencies: {', '.join(missing)}")
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet"] + missing, check=True)

bootstrap()

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.markdown import Markdown
from rich.table import Table
from rich.live import Live
from rich.spinner import Spinner
from rich.text import Text
from rich.columns import Columns
from rich import box
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.styles import Style

# ─── CONSTANTS ────────────────────────────────────────────────────────────────
SCODE_DIR   = Path.home() / ".scode"
MEM_FILE    = SCODE_DIR / "memory.json"
GIST_FILE   = SCODE_DIR / "gist_id.txt"
PLUGINS_DIR = SCODE_DIR / "plugins"
LOG_FILE    = SCODE_DIR / "scode.log"
HIST_FILE   = SCODE_DIR / "history"
VERSION     = "2.0.0"

SCODE_DIR.mkdir(exist_ok=True)
PLUGINS_DIR.mkdir(exist_ok=True)

console = Console()
USER = os.environ.get("USER", "Boss")

# ─── PROVIDERS CONFIG ────────────────────────────────────────────────────────
PROVIDERS = {
    "ollama": {
        "name": "Ollama (Local)",
        "url": "http://localhost:11434/api/chat",
        "key_env": None,
        "default_model": "llama3",
        "type": "ollama",
        "privacy": "🔒 100% Local",
    },
    "openai": {
        "name": "OpenAI",
        "url": "https://api.openai.com/v1/chat/completions",
        "key_env": "OPENAI_API_KEY",
        "default_model": "gpt-4o",
        "type": "openai",
        "privacy": "☁️  Cloud",
    },
    "anthropic": {
        "name": "Anthropic (Claude)",
        "url": "https://api.anthropic.com/v1/messages",
        "key_env": "ANTHROPIC_API_KEY",
        "default_model": "claude-sonnet-4-20250514",
        "type": "anthropic",
        "privacy": "☁️  Cloud",
    },
    "gemini": {
        "name": "Google Gemini",
        "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "key_env": "GEMINI_API_KEY",
        "default_model": "gemini-2.0-flash",
        "type": "openai",
        "privacy": "☁️  Cloud",
    },
    "groq": {
        "name": "Groq (Ultra Fast)",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "key_env": "GROQ_API_KEY",
        "default_model": "llama-3.3-70b-versatile",
        "type": "openai",
        "privacy": "☁️  Cloud",
    },
    "deepseek": {
        "name": "DeepSeek",
        "url": "https://api.deepseek.com/v1/chat/completions",
        "key_env": "DEEPSEEK_API_KEY",
        "default_model": "deepseek-chat",
        "type": "openai",
        "privacy": "☁️  Cloud",
    },
}

# ─── MEMORY ──────────────────────────────────────────────────────────────────
def load_memory():
    if MEM_FILE.exists():
        try:
            with open(MEM_FILE) as f: return json.load(f)
        except: pass
    return {
        "history": [],
        "provider": "ollama",
        "model": "llama3",
        "project_dir": str(Path.cwd()),
        "notes": [],
        "collab_mode": False,
    }

def save_memory(mem):
    with open(MEM_FILE, "w") as f: json.dump(mem, f, indent=2)

# ─── AI ENGINE ───────────────────────────────────────────────────────────────
def build_system_prompt(mem):
    cwd = mem.get("project_dir", str(Path.cwd()))
    notes = "\n".join(mem.get("notes", [])) or "None"
    plugins = get_plugins_context()
    return f"""You are scode v2, an elite terminal AI agent. User: {USER}. 
Project dir: {cwd}
Session notes: {notes}
{plugins}

You have access to these TOOLS. When you want to use one, output EXACTLY this format:
<tool>TOOL_NAME</tool>
<input>INPUT_DATA</input>

Available tools:
- READ_FILE: Read any file. Input: file path
- WRITE_FILE: Write/create file. Input: JSON {{"path":"...","content":"..."}}
- EDIT_FILE: Edit file with diff. Input: JSON {{"path":"...","old":"...","new":"..."}}
- RUN_SHELL: Run shell command. Input: shell command string
- LIST_DIR: List directory. Input: directory path
- GIT_STATUS: Show git status. Input: repo path (optional)
- GIT_DIFF: Show git diff. Input: repo path (optional)
- GIT_COMMIT: Git add+commit. Input: commit message
- SEARCH_FILES: Search in files. Input: JSON {{"pattern":"...","path":"..."}}
- WEB_FETCH: Fetch a URL. Input: URL

Be concise, surgical, brilliant. After tool use, continue your response naturally."""

def call_openai_api(url, api_key, model, messages, system, stream=True):
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}] + messages,
        "stream": stream,
        "max_tokens": 4096,
    }
    req = Request(url, data=json.dumps(payload).encode(), headers=headers)
    with urlopen(req, timeout=60) as resp:
        if not stream:
            data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"]
        full = ""
        for line in resp:
            line = line.decode().strip()
            if line.startswith("data: ") and line != "data: [DONE]":
                try:
                    chunk = json.loads(line[6:])["choices"][0]["delta"].get("content", "")
                    full += chunk
                    yield chunk
                except: pass
        return full

def call_anthropic_api(model, messages, system, stream=True):
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    anth_msgs = []
    for m in messages:
        anth_msgs.append({"role": m["role"], "content": m["content"]})
    payload = {"model": model, "max_tokens": 4096, "system": system, "messages": anth_msgs, "stream": stream}
    req = Request("https://api.anthropic.com/v1/messages", data=json.dumps(payload).encode(), headers=headers)
    with urlopen(req, timeout=60) as resp:
        if not stream:
            data = json.loads(resp.read())
            return data["content"][0]["text"]
        full = ""
        for line in resp:
            line = line.decode().strip()
            if line.startswith("data:"):
                try:
                    evt = json.loads(line[5:].strip())
                    if evt.get("type") == "content_block_delta":
                        chunk = evt["delta"].get("text", "")
                        full += chunk
                        yield chunk
                except: pass
        return full

def call_ollama_api(model, messages, system, stream=True):
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}] + messages,
        "stream": stream,
    }
    req = Request("http://localhost:11434/api/chat", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=120) as resp:
        if not stream:
            return json.loads(resp.read())["message"]["content"]
        full = ""
        for line in resp:
            if line:
                try:
                    data = json.loads(line.decode())
                    chunk = data["message"]["content"]
                    full += chunk
                    yield chunk
                except: pass
        return full

def ask_ai(messages, mem, stream=True):
    provider_id = mem.get("provider", "ollama")
    model       = mem.get("model", "llama3")
    provider    = PROVIDERS.get(provider_id, PROVIDERS["ollama"])
    system      = build_system_prompt(mem)

    try:
        if provider["type"] == "anthropic":
            gen = call_anthropic_api(model, messages, system, stream)
        elif provider["type"] == "ollama":
            gen = call_ollama_api(model, messages, system, stream)
        else:
            key_env = provider.get("key_env")
            api_key = os.environ.get(key_env, "") if key_env else ""
            if not api_key:
                console.print(f"[red]❌ {provider['name']} API key not set. export {key_env}=...[/red]")
                return ""
            url = provider["url"]
            if provider_id == "gemini":
                url = f"{url}?key={api_key}"
            gen = call_openai_api(url, api_key, model, messages, system, stream)

        full_response = ""
        if stream:
            # Collect chunks from generator first
            chunks = []
            for chunk in gen:
                chunks.append(chunk)
                full_response += chunk
            # Print all at once
            if full_response:
                console.print(f"\n[bold green]scode ▸[/bold green] {full_response}")
            else:
                console.print(f"\n[red]❌ Empty response from model. Is Ollama running? Try: ollama serve[/red]")
        else:
            full_response = gen if isinstance(gen, str) else "".join(gen)
        return full_response

    except URLError as e:
        console.print(f"[red]❌ Connection failed: {e}[/red]")
        if provider_id == "ollama":
            console.print("[yellow]💡 Start Ollama: ollama serve[/yellow]")
        return ""
    except Exception as e:
        console.print(f"[red]❌ API Error: {e}[/red]")
        return ""

# ─── TOOLS ENGINE ────────────────────────────────────────────────────────────
def execute_tool(tool_name, tool_input, mem):
    cwd = mem.get("project_dir", str(Path.cwd()))

    if tool_name == "READ_FILE":
        path = Path(tool_input.strip())
        if not path.is_absolute(): path = Path(cwd) / path
        if path.exists():
            content = path.read_text(errors="replace")
            console.print(Panel(Syntax(content, path.suffix.lstrip(".") or "text", theme="monokai", line_numbers=True), title=f"📄 {path}", border_style="blue"))
            return content
        return f"File not found: {path}"

    elif tool_name == "WRITE_FILE":
        data = json.loads(tool_input)
        path = Path(data["path"])
        if not path.is_absolute(): path = Path(cwd) / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data["content"])
        console.print(f"[green]✅ Written: {path}[/green]")
        return f"Written: {path}"

    elif tool_name == "EDIT_FILE":
        data = json.loads(tool_input)
        path = Path(data["path"])
        if not path.is_absolute(): path = Path(cwd) / path
        if not path.exists(): return f"File not found: {path}"
        original = path.read_text()
        if data["old"] not in original:
            return f"❌ String not found in {path}"
        updated = original.replace(data["old"], data["new"], 1)
        # Show diff
        diff = list(difflib.unified_diff(
            original.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile=f"a/{path.name}", tofile=f"b/{path.name}"
        ))
        if diff:
            console.print(Syntax("".join(diff), "diff", theme="monokai"))
        console.print(f"\n[yellow]Apply this edit to {path}? [y/N]: [/yellow]", end="")
        if input().lower() == 'y':
            path.write_text(updated)
            console.print(f"[green]✅ Edited: {path}[/green]")
            return f"Edited: {path}"
        return "Edit cancelled"

    elif tool_name == "RUN_SHELL":
        cmd = tool_input.strip()
        console.print(f"\n[yellow]🔧 Run: [bold]{cmd}[/bold] ? [y/N]: [/yellow]", end="")
        if input().lower() == 'y':
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd)
            output = result.stdout + result.stderr
            if output:
                console.print(Panel(output.strip(), title="Shell Output", border_style="green"))
            return output or "(no output)"
        return "Cancelled"

    elif tool_name == "LIST_DIR":
        path = Path(tool_input.strip()) if tool_input.strip() else Path(cwd)
        if not path.is_absolute(): path = Path(cwd) / path
        if not path.exists(): return f"Not found: {path}"
        items = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name))
        table = Table(box=box.SIMPLE, show_header=False)
        for item in items:
            icon = "📁" if item.is_dir() else "📄"
            size = "" if item.is_dir() else f"[dim]{item.stat().st_size}b[/dim]"
            table.add_row(f"{icon} {item.name}", size)
        console.print(table)
        return "\n".join(str(i) for i in items)

    elif tool_name == "GIT_STATUS":
        result = subprocess.run("git status --short", shell=True, capture_output=True, text=True, cwd=cwd)
        console.print(Panel(result.stdout or "Clean working tree", title="Git Status", border_style="yellow"))
        return result.stdout

    elif tool_name == "GIT_DIFF":
        result = subprocess.run("git diff", shell=True, capture_output=True, text=True, cwd=cwd)
        if result.stdout:
            console.print(Syntax(result.stdout, "diff", theme="monokai"))
        return result.stdout

    elif tool_name == "GIT_COMMIT":
        msg = tool_input.strip()
        result = subprocess.run(f'git add -A && git commit -m "{msg}"', shell=True, capture_output=True, text=True, cwd=cwd)
        console.print(Panel(result.stdout + result.stderr, title="Git Commit", border_style="green"))
        return result.stdout

    elif tool_name == "SEARCH_FILES":
        data = json.loads(tool_input)
        pattern = data.get("pattern", "")
        search_path = data.get("path", cwd)
        result = subprocess.run(f'grep -rn "{pattern}" {search_path} --include="*.py" --include="*.js" --include="*.ts" --include="*.go" --include="*.md" 2>/dev/null | head -30', shell=True, capture_output=True, text=True)
        console.print(Panel(result.stdout or "No matches", title=f"Search: {pattern}", border_style="cyan"))
        return result.stdout

    elif tool_name == "WEB_FETCH":
        url = tool_input.strip()
        try:
            req = Request(url, headers={"User-Agent": "scode/2.0"})
            with urlopen(req, timeout=10) as resp:
                content = resp.read().decode(errors="replace")[:3000]
            console.print(Panel(content[:500] + "...", title=f"🌐 {url}", border_style="blue"))
            return content
        except Exception as e:
            return f"Fetch failed: {e}"

    return f"Unknown tool: {tool_name}"

def process_tool_calls(response, mem):
    """Extract and execute tool calls from AI response."""
    tool_pattern = re.compile(r'<tool>(.*?)</tool>\s*<input>(.*?)</input>', re.DOTALL)
    matches = tool_pattern.findall(response)
    
    tool_results = []
    for tool_name, tool_input in matches:
        tool_name = tool_name.strip()
        tool_input = tool_input.strip()
        console.print(f"\n[cyan]🔧 Tool: [bold]{tool_name}[/bold][/cyan]")
        result = execute_tool(tool_name, tool_input, mem)
        tool_results.append(f"Tool {tool_name} result: {str(result)[:500]}")
    
    return tool_results

# ─── PLUGINS ─────────────────────────────────────────────────────────────────
def get_plugins_context():
    plugins = []
    for f in PLUGINS_DIR.glob("*.py"):
        try:
            content = f.read_text()[:500]
            plugins.append(f"Plugin {f.name}:\n{content}")
        except: pass
    if not plugins: return ""
    return "Loaded plugins:\n" + "\n".join(plugins)

# ─── IMMORTALITY ─────────────────────────────────────────────────────────────
def is_running(pid):
    try: os.kill(pid, 0); return True
    except OSError: return False

def run_watchdog(main_pid):
    while True:
        time.sleep(2)
        if not is_running(main_pid):
            if (SCODE_DIR / "exit_flag").exists(): sys.exit(0)
            subprocess.Popen([sys.executable, os.path.abspath(__file__)])
            sys.exit(0)

def spawn_watchdog():
    wd_pid_file = SCODE_DIR / "wd.pid"
    if wd_pid_file.exists():
        try:
            wd_pid = int(wd_pid_file.read_text())
            if is_running(wd_pid): return
        except: pass
    proc = subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), "--watchdog", str(os.getpid())],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    wd_pid_file.write_text(str(proc.pid))

# ─── GIST BACKUP ─────────────────────────────────────────────────────────────
def gist_backup_loop():
    token = os.environ.get("GITHUB_TOKEN")
    if not token: return
    while True:
        try:
            content = MEM_FILE.read_text()
            headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json", "Content-Type": "application/json"}
            gist_id = GIST_FILE.read_text().strip() if GIST_FILE.exists() else None
            data = json.dumps({"description": "scode v2 memory", "public": False, "files": {"memory.json": {"content": content}}}).encode()
            url = f"https://api.github.com/gists/{gist_id}" if gist_id else "https://api.github.com/gists"
            req = Request(url, data=data, headers=headers, method="PATCH" if gist_id else "POST")
            with urlopen(req) as resp:
                res = json.loads(resp.read())
                if not gist_id: GIST_FILE.write_text(res["id"])
        except: pass
        time.sleep(3600)

# ─── EVOLUTION ────────────────────────────────────────────────────────────────
def evolve_scode(mem):
    console.print(Panel("[bold magenta]🧬 Self-Evolution Initiated[/bold magenta]\nAnalyzing own source code...", border_style="magenta"))
    current_code = Path(__file__).read_text()
    prompt = f"Read your own source code. Add ONE powerful new feature (suggest something useful). Return the ENTIRE updated Python script in a ```python block. Keep all immortality/healing/tool features intact.\n\n```python\n{current_code}\n```"
    response = ask_ai([{"role": "user", "content": prompt}], mem, stream=False)
    match = re.search(r"```python\n(.*?)```", response, re.DOTALL)
    if match:
        Path(__file__).write_text(match.group(1))
        console.print("[green]✅ Evolution complete. Restarting...[/green]")
        os.execv(sys.executable, [sys.executable] + sys.argv)
    else:
        console.print("[red]❌ Evolution aborted — invalid code generated[/red]")

# ─── AUTO-HEAL ────────────────────────────────────────────────────────────────
def auto_heal(err_trace, mem):
    console.print(Panel(f"[red]{err_trace[:500]}[/red]", title="💥 Fatal Error", border_style="red"))
    console.print("[magenta]🔧 Self-Heal Protocol initiated...[/magenta]")
    current_code = Path(__file__).read_text()
    prompt = f"Fix this crash. Return ENTIRE fixed Python script in ```python block.\n\nTraceback:\n{err_trace}\n\nCode:\n```python\n{current_code[:3000]}\n```"
    response = ask_ai([{"role": "user", "content": prompt}], mem, stream=False)
    match = re.search(r"```python\n(.*?)```", response, re.DOTALL)
    if match:
        Path(__file__).write_text(match.group(1))
        console.print("[green]✅ Healed. Restarting...[/green]")
        os.execv(sys.executable, [sys.executable] + sys.argv)
    else:
        console.print("[red]❌ Healing failed. Manual fix needed.[/red]")
        sys.exit(1)

# ─── COMMANDS ────────────────────────────────────────────────────────────────
def cmd_providers():
    table = Table(title="Available Providers", box=box.ROUNDED, border_style="cyan")
    table.add_column("ID", style="bold yellow")
    table.add_column("Name", style="white")
    table.add_column("Privacy", style="green")
    table.add_column("Key Set?", style="cyan")
    for pid, p in PROVIDERS.items():
        key_env = p.get("key_env")
        key_set = "✅ Yes" if (not key_env or os.environ.get(key_env)) else "❌ No"
        table.add_row(pid, p["name"], p["privacy"], key_set)
    console.print(table)

def cmd_switch_provider(provider_id, mem):
    if provider_id not in PROVIDERS:
        console.print(f"[red]Unknown provider. Use: {', '.join(PROVIDERS.keys())}[/red]")
        return mem
    p = PROVIDERS[provider_id]
    mem["provider"] = provider_id
    mem["model"] = p["default_model"]
    console.print(f"[green]✅ Switched to {p['name']} | Model: {p['default_model']} | {p['privacy']}[/green]")
    return mem

def cmd_set_dir(path_str, mem):
    path = Path(path_str).expanduser().resolve()
    if path.exists() and path.is_dir():
        mem["project_dir"] = str(path)
        os.chdir(path)
        console.print(f"[green]✅ Project dir: {path}[/green]")
    else:
        console.print(f"[red]❌ Not a valid directory: {path}[/red]")
    return mem

def cmd_note(note, mem):
    mem.setdefault("notes", []).append(note)
    console.print(f"[green]📝 Note saved[/green]")
    return mem

def cmd_collab(mem):
    mem["collab_mode"] = not mem.get("collab_mode", False)
    state = "ON 🤝" if mem["collab_mode"] else "OFF"
    console.print(f"[cyan]Collab mode: {state}[/cyan]")
    if mem["collab_mode"]:
        console.print("[dim]Share your session: cat ~/.scode/memory.json | gist[/dim]")
    return mem

def cmd_export(history):
    ts = int(time.time())
    export_file = Path.cwd() / f"scode_session_{ts}.md"
    with open(export_file, "w") as f:
        f.write(f"# scode v2 Session Export\n\n")
        for msg in history:
            role = "**You**" if msg["role"] == "user" else "**scode**"
            f.write(f"{role}: {msg['content']}\n\n---\n\n")
    console.print(f"[green]✅ Exported: {export_file}[/green]")

def cmd_help():
    table = Table(box=box.SIMPLE, show_header=False, border_style="dim")
    cmds = [
        ("/provider", "List & switch AI providers"),
        ("/use <id>", "Switch provider (ollama/openai/anthropic/gemini/groq/deepseek)"),
        ("/model <name>", "Set model name"),
        ("/dir <path>", "Set project directory"),
        ("/note <text>", "Add persistent session note"),
        ("/collab", "Toggle collab mode (share context)"),
        ("/files", "List project files"),
        ("/git", "Git status + diff"),
        ("/export", "Export conversation to markdown"),
        ("/evolve", "Self-evolve: AI improves own code"),
        ("/clear", "Clear conversation history"),
        ("/exit", "Exit scode"),
    ]
    for cmd, desc in cmds:
        table.add_row(f"[bold yellow]{cmd}[/bold yellow]", f"[dim]{desc}[/dim]")
    console.print(Panel(table, title="[bold]scode v2 Commands[/bold]", border_style="cyan"))

# ─── BANNER ──────────────────────────────────────────────────────────────────
def print_banner(mem):
    provider = PROVIDERS.get(mem.get("provider", "ollama"), PROVIDERS["ollama"])
    console.print(f"""[bold cyan]
 ██████  ██████  ██████  ██████  ███████ 
██      ██      ██    ██ ██   ██ ██      
 █████  ██      ██    ██ ██   ██ █████   
      ██ ██      ██    ██ ██   ██ ██      
 ██████  ██████  ██████  ██████  ███████ [/bold cyan]
[bold magenta]        v{VERSION} — Your Terminal. Evolved.[/bold magenta]
""")
    console.print(f"[dim]Provider: [bold]{provider['name']}[/bold] | Model: [bold]{mem.get('model')}[/bold] | Privacy: {provider['privacy']}[/dim]")
    console.print(f"[dim]Project:  [bold]{mem.get('project_dir', Path.cwd())}[/bold][/dim]")
    console.print(f"[dim]Gist Sync: {'[green]ON[/green]' if os.environ.get('GITHUB_TOKEN') else '[red]OFF[/red]'} | Type [yellow]/help[/yellow] for commands[/dim]\n")

# ─── PROMPT STYLE ────────────────────────────────────────────────────────────
PROMPT_STYLE = Style.from_dict({
    "prompt": "bold ansicyan",
})

# ─── MAIN LOOP ───────────────────────────────────────────────────────────────
def main_loop():
    spawn_watchdog()
    threading.Thread(target=gist_backup_loop, daemon=True).start()

    exit_flag = SCODE_DIR / "exit_flag"
    if exit_flag.exists(): exit_flag.unlink()

    os.system("clear")
    mem = load_memory()
    print_banner(mem)

    history = mem.get("history", [])
    session = PromptSession(
        history=FileHistory(str(HIST_FILE)),
        auto_suggest=AutoSuggestFromHistory(),
        style=PROMPT_STYLE,
    )

    while True:
        try:
            provider_short = mem.get("provider", "ollama")[:4]
            user_in = session.prompt(f"scode [{provider_short}]▸ ").strip()
            if not user_in: continue

            # ── Commands ──────────────────────────────────────────────────
            if user_in.lower() in ["/exit", "exit", "quit"]:
                exit_flag.touch()
                console.print(f"[magenta]Going dark, {USER}. 👋[/magenta]")
                sys.exit(0)

            elif user_in == "/help":
                cmd_help(); continue

            elif user_in == "/provider":
                cmd_providers(); continue

            elif user_in.startswith("/use "):
                mem = cmd_switch_provider(user_in[5:].strip(), mem)
                save_memory(mem); continue

            elif user_in.startswith("/model "):
                mem["model"] = user_in[7:].strip()
                console.print(f"[green]Model: {mem['model']}[/green]")
                save_memory(mem); continue

            elif user_in.startswith("/dir "):
                mem = cmd_set_dir(user_in[5:].strip(), mem)
                save_memory(mem); continue

            elif user_in.startswith("/note "):
                mem = cmd_note(user_in[6:].strip(), mem)
                save_memory(mem); continue

            elif user_in == "/collab":
                mem = cmd_collab(mem)
                save_memory(mem); continue

            elif user_in in ["/files", "/ls"]:
                execute_tool("LIST_DIR", mem.get("project_dir", "."), mem); continue

            elif user_in == "/git":
                execute_tool("GIT_STATUS", "", mem)
                execute_tool("GIT_DIFF", "", mem); continue

            elif user_in == "/export":
                cmd_export(history); continue

            elif user_in == "/clear":
                history = []
                mem["history"] = []
                save_memory(mem)
                console.print("[green]History cleared[/green]"); continue

            elif user_in == "/evolve":
                evolve_scode(mem); continue

            # ── AI Query ──────────────────────────────────────────────────
            history.append({"role": "user", "content": user_in})
            if len(history) > 30: history = history[-30:]

            response = ask_ai(history, mem, stream=True)

            if response:
                # Process any tool calls in the response
                tool_results = process_tool_calls(response, mem)

                # If tools were used, feed results back for follow-up
                if tool_results:
                    tool_context = "\n".join(tool_results)
                    follow_up_msgs = history + [
                        {"role": "assistant", "content": response},
                        {"role": "user", "content": f"[Tool results]\n{tool_context}\n\nContinue based on these results."}
                    ]
                    follow_up = ask_ai(follow_up_msgs, mem, stream=True)
                    if follow_up:
                        history.append({"role": "assistant", "content": response + "\n" + follow_up})
                    else:
                        history.append({"role": "assistant", "content": response})
                else:
                    history.append({"role": "assistant", "content": response})

                mem["history"] = history
                save_memory(mem)

        except KeyboardInterrupt:
            console.print(f"\n[yellow]Ctrl+C caught. Type /exit to quit.[/yellow]")
        except EOFError:
            break
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")

# ─── ENTRY POINT ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--watchdog":
        run_watchdog(int(sys.argv[2]))
    else:
        try:
            main_loop()
        except Exception as e:
            if not isinstance(e, SystemExit):
                mem = load_memory()
                auto_heal(traceback.format_exc(), mem)
