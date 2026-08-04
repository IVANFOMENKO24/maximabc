import asyncio
import concurrent.futures
import hashlib
import json
import logging
import os
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, CommandStart
from aiogram.types import FSInputFile

from config import (
    BOT_TOKEN,
    CACHE_FILE,
    DB_FILE,
    FFMPEG_PATH,
    LETTERS_FOLDER,
    PHRASE_CACHE_DIR,
    PID_FILE,
    RUSSIAN_LETTERS,
)


def find_ffmpeg() -> str:
    import shutil

    log = lambda msg: logging.info(f"[find_ffmpeg] {msg}")

    if FFMPEG_PATH:
        if os.path.isfile(FFMPEG_PATH):
            log(f"использую config.FFMPEG_PATH: {FFMPEG_PATH}")
            return FFMPEG_PATH
        log(f"config.FFMPEG_PATH={FFMPEG_PATH!r} не является файлом")

    for name in ("ffmpeg", "ffmpeg.exe"):
        which_path = shutil.which(name)
        if which_path and os.path.isfile(which_path):
            log(f"shutil.which({name!r}) -> {which_path}")
            return which_path

    appdata_local = os.environ.get("LOCALAPPDATA") or ""
    if appdata_local:
        capcut_root = os.path.join(appdata_local, "CapCut", "Apps")
        if os.path.isdir(capcut_root):
            try:
                for item in sorted(os.listdir(capcut_root), reverse=True):
                    cand = os.path.join(capcut_root, item, "ffmpeg.exe")
                    if os.path.isfile(cand):
                        log(f"CapCut found: {cand}")
                        return cand
            except OSError as e:
                log(f"CapCut scan error: {e}")

        winget_root = os.path.join(appdata_local, "Microsoft", "WinGet", "Packages")
        if os.path.isdir(winget_root):
            try:
                for pkg_name in sorted(os.listdir(winget_root), reverse=True):
                    if "ffmpeg" in pkg_name.lower():
                        pkg_dir = os.path.join(winget_root, pkg_name)
                        for root, _, files in os.walk(pkg_dir):
                            if "ffmpeg.exe" in files:
                                cand = os.path.join(root, "ffmpeg.exe")
                                if os.path.isfile(cand):
                                    log(f"WinGet found: {cand}")
                                    return cand
            except OSError as e:
                log(f"WinGet scan error: {e}")

    home = os.path.expanduser("~")
    candidates = [
        "/usr/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
        "/opt/homebrew/bin/ffmpeg",
        "/opt/homebrew/sbin/ffmpeg",
        "/usr/pkg/bin/ffmpeg",
        "/snap/bin/ffmpeg",
        "/opt/ffmpeg/bin/ffmpeg",
        "/opt/ffmpeg/ffmpeg",
        "/usr/local/ffmpeg/bin/ffmpeg",
        "/home/bin/ffmpeg",
        os.path.join(home, ".local", "bin", "ffmpeg"),
        os.path.join(home, "bin", "ffmpeg"),
        os.path.join(home, ".nix-profile", "bin", "ffmpeg"),
        r"C:\Program Files\FFmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\Gyan\FFmpeg\bin\ffmpeg.exe",
        r"C:\FFmpeg\bin\ffmpeg.exe",
        r"C:\ffmpeg\bin\ffmpeg.exe",
    ]

    for c in candidates:
        try:
            if os.path.isfile(c):
                log(f"candidate found: {c}")
                return c
        except OSError:
            continue

    env_path = os.environ.get("PATH", "")
    if env_path:
        for d in env_path.split(os.pathsep):
            if not d:
                continue
            for name in ("ffmpeg", "ffmpeg.exe"):
                cand = os.path.join(d, name)
                try:
                    if os.path.isfile(cand):
                        log(f"PATH found: {cand}")
                        return cand
                except OSError:
                    continue

    nix_root = "/nix/store"
    if os.path.isdir(nix_root):
        try:
            for entry in sorted(os.listdir(nix_root), reverse=True):
                if "ffmpeg" in entry.lower():
                    cand = os.path.join(nix_root, entry, "bin", "ffmpeg")
                    if os.path.isfile(cand):
                        log(f"nix found: {cand}")
                        return cand
        except OSError as e:
            log(f"nix scan error: {e}")

    if os.name == "nt":
        drives = [f"{d}:\\" for d in "CDEFGHIJKLMNOPQRSTUVWXYZ" if os.path.isdir(f"{d}:\\")]
    else:
        drives = ["/usr", "/opt", "/home", "/nix", "/snap", "/app", "/var", "/bin", "/sbin"]
        if os.path.isdir(home) and home not in drives:
            drives.insert(0, home)

    for root in drives:
        if not os.path.isdir(root):
            continue
        try:
            for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
                try:
                    for name in filenames:
                        if name in ("ffmpeg", "ffmpeg.exe"):
                            cand = os.path.join(dirpath, name)
                            try:
                                if os.path.isfile(cand):
                                    logging.info(f"find_ffmpeg found via walk {root}: {cand}")
                                    return cand
                            except OSError:
                                pass
                    for skip in ("proc", "sys", "dev", "$Recycle.Bin", "System Volume Information", "Windows"):
                        if skip in dirnames:
                            dirnames.remove(skip)
                except (PermissionError, OSError):
                    continue
        except (PermissionError, OSError):
            continue

    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.isfile(exe):
            log(f"imageio_ffmpeg fallback: {exe}")
            try:
                os.chmod(exe, 0o755)
            except OSError:
                pass
            return exe
    except Exception as e:
        log(f"imageio-ffmpeg не доступен: {e}")

    logging.warning("find_ffmpeg: бинарник не найден, возвращаю 'ffmpeg' как есть (отправка кружков сломается)")
    return "ffmpeg"


def check_ffmpeg(binary: str) -> tuple[bool, str]:
    try:
        env = os.environ.copy()
        env["PATH"] = os.environ.get("PATH", "")
        r = subprocess.run(
            [binary, "-version"],
            capture_output=True, text=True, timeout=20, env=env,
        )
        if r.returncode == 0:
            first_line = (r.stdout or "").splitlines()[0] if (r.stdout or "").splitlines() else "ok"
            return True, first_line.strip()
        err_tail = (r.stderr or "").strip().splitlines()[-1] if (r.stderr or "").strip().splitlines() else ""
        return False, f"exit code {r.returncode}: {err_tail[:200]}"
    except FileNotFoundError:
        return False, "binary not found (FileNotFoundError)"
    except PermissionError as e:
        return False, f"permission denied: {e}"
    except subprocess.TimeoutExpired:
        return False, "timeout calling --version (20s)"
    except OSError as e:
        return False, f"OS error ({type(e).__name__}): {e}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


FFMPEG_BIN: str = ""

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

_process_pool: concurrent.futures.ProcessPoolExecutor | None = None
_io_pool: concurrent.futures.ThreadPoolExecutor | None = None
_concat_sem: asyncio.Semaphore | None = None


def _get_pools() -> tuple[
    concurrent.futures.ThreadPoolExecutor,
    concurrent.futures.ProcessPoolExecutor | None,
    asyncio.Semaphore,
]:
    global _io_pool, _process_pool, _concat_sem
    if _io_pool is None:
        import multiprocessing
        cpu = min(4, max(1, (multiprocessing.cpu_count() or 1)))
        _io_pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=max(4, cpu * 2),
            thread_name_prefix="bot_io",
        )
        try:
            _process_pool = concurrent.futures.ProcessPoolExecutor(max_workers=cpu)
        except Exception:
            _process_pool = None
        _concat_sem = asyncio.Semaphore(max(1, cpu))
    assert _io_pool is not None and _concat_sem is not None
    return _io_pool, _process_pool, _concat_sem


def _pid_alive(pid: int) -> bool:
    try:
        if os.name == "nt":
            proc = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                 f"Get-Process -Id {pid} -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Id"],
                capture_output=True, text=True, timeout=10,
            )
            return proc.returncode == 0 and str(pid) in (proc.stdout or "")
        else:
            os.kill(pid, 0)
        return True
    except OSError:
        return False
    except Exception:
        return False


def _in_container() -> bool:
    try:
        if os.path.isfile("/.dockerenv") or os.path.isfile("/run/.containerenv"):
            return True
    except Exception:
        pass
    try:
        with open("/proc/1/cgroup", "r", errors="ignore") as f:
            data = f.read()
        if "docker" in data or "kubepods" in data or "lxc" in data or "containerd" in data:
            return True
    except Exception:
        pass
    return False


def acquire_bot_lock() -> None:
    my_pid = os.getpid()
    if my_pid == 1 or _in_container():
        logging.info(
            "PID-lock пропущен: мы внутри контейнера (PID 1 или /.dockerenv). "
            "Хостинг сам гарантирует один экземпляр."
        )
        try:
            if os.path.exists(PID_FILE):
                try:
                    os.remove(PID_FILE)
                except OSError:
                    pass
            with open(PID_FILE, "w") as f:
                f.write(str(my_pid))
        except OSError:
            pass
        return

    old_pid: int | None = None
    try:
        if os.path.exists(PID_FILE):
            try:
                with open(PID_FILE, "r") as f:
                    data = f.read().strip()
                if data.isdigit():
                    old_pid = int(data)
            except (OSError, ValueError):
                old_pid = None
    except Exception:
        old_pid = None

    if old_pid is not None and old_pid == my_pid:
        old_pid = None

    if old_pid is not None and old_pid == 1:
        logging.warning(f"PID-файл указывает на PID 1 (init/контейнер) — игнорирую, не убиваю.")
        old_pid = None

    if old_pid is not None and _pid_alive(old_pid):
        logging.warning(f"Обнаружен запущенный экземпляр бота (PID {old_pid}). Убиваю его, чтобы избежать ConflictError.")
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill.exe", "/F", "/PID", str(old_pid)],
                    capture_output=True, timeout=15,
                )
            else:
                os.kill(old_pid, 15)
            for _ in range(20):
                if not _pid_alive(old_pid):
                    break
                time.sleep(0.25)
            else:
                if os.name != "nt":
                    try:
                        os.kill(old_pid, 9)
                    except OSError:
                        pass
        except Exception as e:
            logging.error(f"Не удалось убить старый процесс PID {old_pid}: {e}")

    try:
        with open(PID_FILE, "w") as f:
            f.write(str(os.getpid()))
    except OSError as e:
        logging.warning(f"Не могу записать PID-файл {PID_FILE}: {e}")


import signal
import time

_registered_cleanup = False


def _register_cleanup() -> None:
    global _registered_cleanup
    if _registered_cleanup:
        return
    _registered_cleanup = True

    def _cleanup(*_args):
        try:
            if os.path.exists(PID_FILE):
                try:
                    with open(PID_FILE, "r") as f:
                        stored = f.read().strip()
                except OSError:
                    stored = ""
                if stored == str(os.getpid()):
                    try:
                        os.remove(PID_FILE)
                    except OSError:
                        pass
        except Exception:
            pass

    try:
        signal.signal(signal.SIGINT, _cleanup)
        signal.signal(signal.SIGTERM, _cleanup)
    except Exception:
        pass
    import atexit
    atexit.register(_cleanup)


def init_db() -> None:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            first_name TEXT,
            text TEXT NOT NULL,
            timestamp DATETIME NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            first_seen DATETIME NOT NULL,
            message_count INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()


def log_message(user_id: int, username: str | None, first_name: str | None, text: str) -> None:
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        now = datetime.now().isoformat()

        cursor.execute("INSERT INTO messages (user_id, username, first_name, text, timestamp) VALUES (?, ?, ?, ?, ?)",
                       (user_id, username, first_name, text, now))

        cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if row:
            cursor.execute("UPDATE users SET message_count = message_count + 1, username = ?, first_name = ? WHERE user_id = ?",
                           (username, first_name, user_id))
        else:
            cursor.execute("INSERT INTO users (user_id, username, first_name, first_seen, message_count) VALUES (?, ?, ?, ?, 1)",
                           (user_id, username, first_name, now))

        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"DB error: {e}")


def load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_cache(cache: dict) -> None:
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Не удалось сохранить кэш: {e}")


CACHE = load_cache()


def get_letter_file_path(letter: str) -> str | None:
    possible_names = [
        f"{letter}.mp4",
        f"{letter.upper()}.mp4",
    ]
    for name in possible_names:
        path = os.path.join(LETTERS_FOLDER, name)
        if os.path.isfile(path):
            return path
    return None


def phrase_hash(letters: list[str]) -> str:
    return hashlib.md5("".join(letters).encode("utf-8")).hexdigest()


def _concat_worker(
    ffmpeg_bin: str, letter_paths: list[str], output_path: str,
) -> bool:
    work_dir = tempfile.mkdtemp(prefix="tgletter_")
    list_file_path = os.path.join(work_dir, "files.txt")
    try:
        norm_paths: list[str] = []
        for i, p in enumerate(letter_paths):
            norm_out = os.path.join(work_dir, f"norm_{i:04d}.mp4")
            norm_cmd = [
                ffmpeg_bin, "-y",
                "-i", p,
                "-map", "0:v:0", "-map", "0:a:0?",
                "-vf", "fps=30,format=yuv420p",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-ar", "48000", "-ac", "1", "-b:a", "96k",
                "-video_track_timescale", "15360",
                "-movflags", "+faststart",
                norm_out,
            ]
            r = subprocess.run(norm_cmd, capture_output=True, text=True)
            if r.returncode != 0:
                logging.error(f"normalize {p} failed: {r.stderr}")
                return False
            norm_paths.append(norm_out)

        with open(list_file_path, "w", encoding="utf-8") as f:
            for p in norm_paths:
                escaped = p.replace("'", "'\\''")
                f.write(f"file '{escaped}'\n")

        concat_out = os.path.join(work_dir, "concat.mp4")
        concat_cmd = [
            ffmpeg_bin, "-y",
            "-f", "concat", "-safe", "0",
            "-i", list_file_path,
            "-c", "copy",
            concat_out,
        ]
        r = subprocess.run(concat_cmd, capture_output=True, text=True)
        if r.returncode != 0:
            logging.error(f"ffmpeg concat failed: {r.stderr}")
            return False

        vf = (
            "scale=360:360:force_original_aspect_ratio=decrease,"
            "pad=360:360:(ow-iw)/2:(oh-ih)/2:color=black,"
            "setsar=1,format=yuv420p,fps=30"
        )
        reencode_cmd = [
            ffmpeg_bin, "-y",
            "-t", "60",
            "-i", concat_out,
            "-vf", vf,
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ar", "48000", "-ac", "1", "-b:a", "96k",
            "-movflags", "+faststart",
            output_path,
        ]
        r2 = subprocess.run(reencode_cmd, capture_output=True, text=True)
        if r2.returncode != 0:
            logging.error(f"ffmpeg reencode failed: {r2.stderr}")
            return False
        return True
    finally:
        try:
            for root, _, files in os.walk(work_dir, topdown=False):
                for name in files:
                    try:
                        os.remove(os.path.join(root, name))
                    except OSError:
                        pass
                try:
                    os.rmdir(root)
                except OSError:
                    pass
        except OSError:
            pass


async def concat_letter_videos_async(letter_paths: list[str], output_path: str) -> bool:
    io_pool, proc_pool, sem = _get_pools()
    loop = asyncio.get_running_loop()
    async with sem:
        try:
            if proc_pool is not None:
                try:
                    return await loop.run_in_executor(
                        proc_pool,
                        _concat_worker,
                        FFMPEG_BIN, list(letter_paths), output_path,
                    )
                except Exception as e:
                    logging.warning(f"process pool concat failed, fallback to thread: {e}")
            return await loop.run_in_executor(
                io_pool,
                _concat_worker,
                FFMPEG_BIN, list(letter_paths), output_path,
            )
        except concurrent.futures.CancelledError:
            return False
        except Exception as e:
            logging.error(f"concat async error: {e}")
            return False


def concat_letter_videos(letter_paths: list[str], output_path: str) -> bool:
    return _concat_worker(FFMPEG_BIN, letter_paths, output_path)


@dp.message(CommandStart())
async def command_start_handler(message: types.Message) -> None:
    user_id = message.from_user.id if message.from_user else 0
    username = message.from_user.username if message.from_user else None
    first_name = message.from_user.first_name if message.from_user else None
    log_message(user_id, username, first_name, message.text or "/start")

    phrase_count = sum(1 for k in CACHE if k.startswith("phrase:"))
    await message.answer(
        "здарова бродяга, отправь мне любой текст, и я склею все буквы в один кружок телеграмма, "
        "отрпавишь кенту, пока разраб бота включил ноут. "
        "Если чо первая отправка фразы будет чуть медленнее, потом будет быстрее из-за кэша! хехе\n\n"
        f"⚡ В кэше фраз: {phrase_count}"
    )


@dp.message(Command("stats"))
async def command_stats_handler(message: types.Message) -> None:
    user_id = message.from_user.id if message.from_user else 0
    username = message.from_user.username if message.from_user else None
    first_name = message.from_user.first_name if message.from_user else None
    log_message(user_id, username, first_name, message.text or "/stats")

    parts = (message.text or "").strip().split()
    if len(parts) < 2 or parts[1] != "56890":
        return

    try:
        await message.delete()
    except Exception:
        pass

    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM messages")
        total_messages = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]

        cursor.execute("""
            SELECT text, COUNT(*) as cnt
            FROM messages
            GROUP BY text
            ORDER BY cnt DESC
            LIMIT 10
        """)
        top_words = cursor.fetchall()

        cursor.execute("""
            SELECT first_name, username, message_count
            FROM users
            ORDER BY message_count DESC
            LIMIT 10
        """)
        top_users = cursor.fetchall()

        cursor.execute("""
            SELECT m.first_name, m.username, m.text, m.timestamp
            FROM messages m
            ORDER BY m.timestamp DESC
            LIMIT 15
        """)
        recent = cursor.fetchall()

        conn.close()

        reply = "📊 Статистика бота:\n\n"
        reply += f"👥 Всего пользователей: {total_users}\n"
        reply += f"💬 Всего сообщений: {total_messages}\n\n"

        reply += "🔥 Топ-10 слов/фраз:\n"
        if top_words:
            for i, (text, cnt) in enumerate(top_words, 1):
                display_text = text[:30] + ("..." if len(text) > 30 else "")
                reply += f"{i}. «{display_text}» — {cnt} раз\n"
        else:
            reply += "Пока пусто\n"

        reply += "\n🏆 Топ-10 пользователей:\n"
        if top_users:
            for i, (fname, uname, cnt) in enumerate(top_users, 1):
                name = fname or uname or str("Аноним")
                reply += f"{i}. {name} — {cnt} сообщений\n"
        else:
            reply += "Пока пусто\n"

        reply += "\n🕐 Последние 15 сообщений:\n"
        if recent:
            for i, (fname, uname, text, ts) in enumerate(recent, 1):
                name = fname or uname or "Аноним"
                try:
                    dt = datetime.fromisoformat(ts).strftime("%H:%M")
                except Exception:
                    dt = ts[:5]
                display_text = text[:25] + ("..." if len(text) > 25 else "")
                reply += f"{i}. [{dt}] {name}: «{display_text}»\n"
        else:
            reply += "Пока пусто\n"

        await message.answer(reply)
    except Exception as e:
        logging.error(f"Stats error: {e}")
        try:
            await message.answer(f"Ошибка при получении статистики: {e}")
        except Exception:
            pass


@dp.message()
async def text_handler(message: types.Message) -> None:
    text = message.text or message.caption
    if not text:
        await message.answer("Отправь мне текст!")
        return

    user_id = message.from_user.id if message.from_user else 0
    username = message.from_user.username if message.from_user else None
    first_name = message.from_user.first_name if message.from_user else None

    log_message(user_id, username, first_name, text)

    if text.startswith("/"):
        return

    text_lower = text.lower()
    letters: list[str] = []
    missing_letters: list[str] = []

    for char in text_lower:
        if char == " ":
            continue
        if char not in RUSSIAN_LETTERS:
            continue
        letters.append(char)

    if not letters:
        await message.answer("В тексте не найдено русских букв для отправки.")
        return

    letter_paths: list[str] = []
    for letter in letters:
        path = get_letter_file_path(letter)
        if path:
            letter_paths.append(path)
        else:
            missing_letters.append(letter)

    if missing_letters:
        missing = ", ".join(set(missing_letters))
        await message.answer(f"⚠️ Не найдены файлы для букв: {missing}")
        if not letter_paths:
            return

    if len(letter_paths) < len(letters):
        await message.answer("⚠️ Часть букв не найдена, кружок будет из оставшихся.")

    cache_key = "phrase:" + phrase_hash(letters)
    cache_changed = False

    ffmpeg_ok, ffmpeg_info = check_ffmpeg(FFMPEG_BIN)
    if not ffmpeg_ok and cache_key not in CACHE:
        logging.error(
            f"FFmpeg check FAILED before handling phrase. "
            f"Used FFMPEG_BIN={FFMPEG_BIN!r}, info={ffmpeg_info}. "
            f"Install hint: apt-get install -y ffmpeg (Debian/Ubuntu), dnf install -y ffmpeg (CentOS/Fedora), "
            f"brew install ffmpeg (macOS). Or set env var FFMPEG_PATH to absolute binary path."
        )
        await message.answer(
            "⚠️ Временно не могу создать кружок — серверные настройки подлечивают.\n"
            "Админ уже в курсе, скоро всё починят 🙏"
        )
        return

    status_msg = await message.answer("Подготавливаю кружок...")

    try:
        if cache_key in CACHE:
            try:
                await bot.send_video_note(
                    chat_id=message.chat.id,
                    video_note=CACHE[cache_key]
                )
                try:
                    await status_msg.edit_text("Готово!")
                except Exception:
                    pass
                return
            except Exception as e:
                logging.warning(f"Не удалось отправить по кэшированному file_id: {e}, пробуем файлом.")

        output_filename = phrase_hash(letters) + ".mp4"
        output_path = os.path.join(PHRASE_CACHE_DIR, output_filename)

        if not os.path.exists(output_path):
            try:
                await status_msg.edit_text("Склеиваю видео...")
            except Exception:
                pass
            ok = await concat_letter_videos_async(letter_paths, output_path)
            if not ok:
                try:
                    await status_msg.edit_text(
                        "❌ Ошибка при склейке видео. Возможно, не установлен ffmpeg.\n"
                        "Установи ffmpeg и добавь его в PATH (https://ffmpeg.org/download.html)."
                    )
                except Exception:
                    pass
                return

        input_file = FSInputFile(output_path)
        sent = await bot.send_video_note(
            chat_id=message.chat.id,
            video_note=input_file
        )

        if sent.video_note:
            new_file_id = sent.video_note.file_id
            CACHE[cache_key] = new_file_id
            cache_changed = True
            logging.info(f"Сохранен file_id для фразы ({len(letters)} букв): {new_file_id}")

        try:
            await status_msg.edit_text("Готово!")
        except Exception:
            pass

    except Exception as e:
        logging.error(f"Ошибка при отправке кружка: {e}")
        try:
            await status_msg.edit_text(f"❌ Ошибка: {e}")
        except Exception:
            pass

    finally:
        if cache_changed:
            save_cache(CACHE)


def _runtime_install_ffmpeg() -> bool:
    if os.name != "posix":
        return False
    try:
        import ctypes
        is_root = False
        try:
            is_root = ctypes.CDLL("libc.so.6").geteuid() == 0
        except Exception:
            is_root = os.geteuid() == 0 if hasattr(os, "geteuid") else False
        if not is_root:
            return False
    except Exception:
        return False

    env = os.environ.copy()
    env["DEBIAN_FRONTEND"] = "noninteractive"
    env["PATH"] = (
        "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/opt/homebrew/bin:"
        + env.get("PATH", "")
    )

    def _run(cmd: list[str], timeout: int = 300) -> tuple[int, str]:
        try:
            r = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout, env=env,
            )
            return r.returncode, (r.stderr or "") + (r.stdout or "")
        except FileNotFoundError as e:
            return 127, f"binary not found: {e}"
        except Exception as e:
            return 1, str(e)

    def _which(name: str) -> str | None:
        import shutil as _s
        w = _s.which(name, path=env.get("PATH"))
        if w and os.path.isfile(w):
            return w
        for p in env.get("PATH", "").split(os.pathsep):
            c = os.path.join(p, name)
            if os.path.isfile(c):
                return c
        return None

    def _locate_ffmpeg() -> str | None:
        import shutil as _s
        fresh = _s.which("ffmpeg") or _s.which("ffmpeg", path=env.get("PATH"))
        if fresh:
            return fresh
        for p in ("/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/bin/ffmpeg", "/opt/homebrew/bin/ffmpeg"):
            if os.path.isfile(p):
                return p
        return None

    apt_get = _which("apt-get")
    apk = _which("apk")
    dnf = _which("dnf") or _which("yum")

    if apt_get:
        logging.info("FFmpeg не найден, пробую автоматически поставить через apt-get (может занять 1-2 мин)...")
        rc, out = _run([apt_get, "-y", "update"], 120)
        if rc != 0:
            logging.warning(f"apt-get update failed (rc={rc}): {out[-300:]}")
        rc, out = _run(
            [apt_get, "-y", "--no-install-recommends", "install", "ffmpeg", "ca-certificates"],
            420,
        )
        if rc == 0:
            logging.info("apt-get install ffmpeg завершён успешно, перепроверяю...")
            fresh = _locate_ffmpeg()
            if fresh:
                global FFMPEG_BIN
                FFMPEG_BIN = fresh
                return True
        else:
            logging.error(f"apt-get install ffmpeg failed (rc={rc}): {out[-500:]}")

    if apk:
        logging.info("FFmpeg не найден, пробую автоматически поставить через apk add (Alpine)...")
        rc, out = _run([apk, "add", "--no-cache", "ffmpeg", "ca-certificates"], 300)
        if rc == 0:
            fresh = _locate_ffmpeg()
            if fresh:
                FFMPEG_BIN = fresh
                return True
        else:
            logging.error(f"apk add ffmpeg failed (rc={rc}): {out[-500:]}")

    if dnf:
        logging.info("FFmpeg не найден, пробую автоматически поставить через dnf/yum...")
        rc, out = _run([dnf, "-y", "install", "ffmpeg"], 600)
        if rc == 0:
            fresh = _locate_ffmpeg()
            if fresh:
                FFMPEG_BIN = fresh
                return True
        else:
            logging.error(f"{dnf} install ffmpeg failed (rc={rc}): {out[-500:]}")

    return False


async def main() -> None:
    global FFMPEG_BIN
    _register_cleanup()
    acquire_bot_lock()
    init_db()
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    FFMPEG_BIN = find_ffmpeg()

    ok, info = check_ffmpeg(FFMPEG_BIN)
    if not ok:
        try:
            if _runtime_install_ffmpeg():
                ok, info = check_ffmpeg(FFMPEG_BIN)
        except Exception as e:
            logging.warning(f"runtime ffmpeg install attempt error: {e}")

    if ok:
        logging.info(f"FFmpeg найден: {FFMPEG_BIN} — {info}")
    else:
        msg = (
            f"❌ FFmpeg НЕ НАЙДЕН (использовался путь: {FFMPEG_BIN}). Причина: {info}\n"
            f"   Установи FFmpeg:\n"
            f"     • Linux/Debian/Ubuntu:  sudo apt-get update && sudo apt-get install -y ffmpeg\n"
            f"     • Linux/CentOS/Fedora:  sudo dnf install -y ffmpeg\n"
            f"     • macOS (brew):          brew install ffmpeg\n"
            f"     • Windows (winget):      winget install -e --id Gyan.FFmpeg\n"
            f"     • Или задай точный путь через переменную окружения FFMPEG_PATH или config.FFMPEG_PATH\n"
            f"   Бот запустится, но отправка кружков будет падать с ошибкой."
        )
        logging.error(msg)

    await dp.start_polling(bot, drop_pending_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
