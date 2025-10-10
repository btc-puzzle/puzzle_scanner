import json
import os
import subprocess
import hashlib
import requests
import time
import sys
import random
import string
import traceback
import uuid
import errno
import builtins
from datetime import datetime


def force_blocking_stdio():
    try:
        try:
            if hasattr(os, "set_blocking"):
                try:
                    os.set_blocking(sys.stdout.fileno(), True)
                except Exception:
                    pass
                try:
                    os.set_blocking(sys.stderr.fileno(), True)
                except Exception:
                    pass
                return
        except Exception:
            pass

        try:
            import fcntl
            for stream in (sys.stdout, sys.stderr):
                try:
                    fd = stream.fileno()
                except Exception:
                    continue
                try:
                    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
                    fcntl.fcntl(fd, fcntl.F_SETFL, flags & ~os.O_NONBLOCK)
                except Exception:
                    pass
        except Exception:
            pass
    except Exception:
        pass


def safe_write(s: str):
    while True:
        try:
            sys.stdout.write(s)
            sys.stdout.flush()
            return
        except (BlockingIOError, OSError) as e:
            err = getattr(e, "errno", None)
            if isinstance(e, BlockingIOError) or err in (errno.EAGAIN, errno.EWOULDBLOCK):
                time.sleep(0.01)
                continue
            raise


def safe_print(*args, **kwargs):
    sep = kwargs.get("sep", " ")
    end = kwargs.get("end", "\n")
    text = sep.join(str(a) for a in args) + end
    safe_write(text)


force_blocking_stdio()
builtins.print = safe_print


def now_str():
    try:
        return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    except Exception:
        return time.strftime("%Y-%m-%d %H:%M:%S")

def format_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


# 根据系统选择VanitySearch路径
if os.name == 'nt':
    VANITYSEARCH_PATH = "VanitySearch.exe"
else:
    VANITYSEARCH_PATH = "./vanitysearch"

API_URL = "https://btc-puzzle.com/api"
CONFIG_FILE = "config.json"
TEMP_ADDR_FILE = "addresses_temp.txt"
TARGET_FIXED_ADDR = "1PWo3JeB9jrGwfHDNpdGK54CRas7fsVzXU"

# 按任意键退出
def getch():
    if os.name == 'nt':
        import msvcrt
        return msvcrt.getch()
    else:
        import sys as _sys, tty, termios
        fd = _sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = _sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        return ch

# 获取GPU名称
def get_gpu_model():
    try:
        output = subprocess.check_output(
            "nvidia-smi --query-gpu=name --format=csv,noheader",
            shell=True, stderr=subprocess.DEVNULL
        )
        gpu_model = output.decode('utf-8').strip().split('\n')[0]
        if gpu_model:
            if "NVIDIA GeForce " in gpu_model:
                gpu_model = gpu_model.replace("NVIDIA GeForce ", "")
            return gpu_model
    except Exception:
        pass
    try:
        output = subprocess.check_output("lspci | grep -i 'vga\\|3d\\|2d'", shell=True)
        gpu_line = output.decode('utf-8').split('\n')[0]
        gpu_line = gpu_line.strip() if gpu_line.strip() else "Unknown GPU"
        if "NVIDIA GeForce " in gpu_line:
            gpu_line = gpu_line.replace("NVIDIA GeForce ", "")
        return gpu_line
    except Exception:
        return "Unknown GPU"

# 加载配置文件
def load_config():
    if not os.path.exists(CONFIG_FILE):
        print(f"配置文件 {CONFIG_FILE} 不存在，请先创建！")
        sys.exit(1)

    try:
        with open(CONFIG_FILE, "r", encoding='utf-8') as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        print("配置文件格式错误：", e)
        sys.exit(1)

    for key in ["nickname", "token", "gpuId", "workername", "prefix"]:
        if key not in config:
            print(f"配置文件中缺少必要字段：{key}")
            sys.exit(1)

    gpu_id = str(config["gpuId"])
    if not gpu_id.isdigit():
        print("配置文件中 gpuId 字段必须为数字！")
        sys.exit(1)
    config["gpuId"] = gpu_id

    try:
        numberof1 = int(config["numberof1"])
        if numberof1 < 1 or numberof1 > 27:
            print("配置文件中 numberof1 必须为 1 到 27 之间的数字！")
            sys.exit(1)
    except Exception:
        print("配置文件中 numberof1 必须为数字！")
        sys.exit(1)
    config["numberof1"] = str(numberof1)
    config["device_name"] = get_gpu_model()
    return config

# 获取范围
def get_range(config):
    url = API_URL.rstrip("/") + "/get_range"
    headers = {"Authorization": config["token"]}

    payload = {
        "nickname": config["nickname"],
        "device_name": config.get("device_name", ""),
        "workername": config["workername"],
        "numberof1": config["numberof1"],
        "run_id": config["run_id"]
    }

    prefix = config.get("prefix", "None")
    if prefix and prefix != "None":
        if len(prefix) > 7:
            raise ValueError("prefix 长度必须小于等于7")
        valid_hex = set("0123456789ABCDEFabcdef")
        if not all(c in valid_hex for c in prefix):
            raise ValueError("prefix 必须只包含十六进制字符")
        if prefix[0].lower() not in ('4', '5', '6', '7'):
            raise ValueError("prefix 必须以 4 或 5 或 6 或 7 开头")
        payload["prefix"] = prefix

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        data = response.json()
        return data
    except Exception as e:
        print("请求获取范围失败:", e)
        return {"success": False, "message": "请稍后重试。"}

# 提交范围
def submit_range(config, range_value, proof_of_work, device_name, server_worker):
    url = API_URL.rstrip("/") + "/submit_range"
    headers = {"Authorization": config["token"]}
    payload = {
        "range": range_value,
        "proof_of_work": proof_of_work,
        "device_name": device_name,
        "workername": server_worker,
        "run_id":    config["run_id"],
        "numberof1": config["numberof1"]
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        return response.json()
    except Exception as e:
        print("提交范围失败:", e)
        return {"success": False, "message": str(e)}
        
def _is_transient_dns_error(msg: str) -> bool:
    if not msg:
        return False
    m = msg.lower()
    keywords = [
        "nameresolutionerror",
        "failed to resolve",
        "temporary failure in name resolution",
        "max retries exceeded with url",
        "failed to establish a new connection",
        "httpsconnectionpool", 
    ]
    return any(k in m for k in keywords)


def submit_range_until_success(config, range_value, proof_of_work, device_name, server_worker,
                               min_delay: int = 1, max_delay: int = 20):
    attempt = 1
    delay = min_delay
    while True:
        resp = submit_range(config, range_value, proof_of_work, device_name, server_worker)
        if resp.get("success"):
            if attempt > 1:
                print(f"范围提交在第 {attempt} 次重试后成功。")
            return resp

        msg = str(resp.get("message", ""))
        if _is_transient_dns_error(msg):
            print(f"提交范围失败（第 {attempt} 次，{now_str()}）：{msg}")
            print(f"检测到临时网络/解析问题，将在 {delay} 秒后重试……（Ctrl+C 可中断）")
            try:
                jitter = random.uniform(0, min(10, delay))
                time.sleep(delay + jitter)
            except KeyboardInterrupt:
                print("\n检测到 Ctrl+C，已停止重试。")
                return resp
            attempt += 1
            delay = min(delay * 2, max_delay)
            continue

        return resp


# 计算工作证明
def compute_sha256_sum(private_keys):
    total = 0
    for pk in private_keys:
        h = hashlib.sha256(pk.encode('utf-8')).hexdigest()
        total += int(h, 16)
    return hex(total)[2:]

# 写入地址
def write_addresses_file(addresses):
    with open(TEMP_ADDR_FILE, "w") as f:
        for addr in addresses:
            f.write(addr.strip() + "\n")
        f.write(TARGET_FIXED_ADDR + "\n")

# 扫描主程序
def run_vanitysearch(config, range_value, addresses):
    write_addresses_file(addresses)
    start = f"{range_value}00000000000"
    cmd = [
        VANITYSEARCH_PATH,
        "-gpuId", config["gpuId"],
        "-i", TEMP_ADDR_FILE,
        "-start", start,
        "-range", "44"
    ]

    scan_start_wall = now_str()
    scan_start_perf = time.perf_counter()
    print("【    开始时间    】：", scan_start_wall)
    print("【    扫描中...   】")

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    found_keys = []
    found_target = False
    target_result = {}
    speed_line = ""
    current_line = ""

    last_draw_ts = 0.0
    draw_interval = 0.10  # 100ms
    last_draw_len = 0

    try:
        ansi_supported = sys.stdout.isatty()
    except Exception:
        ansi_supported = False

    final_status_line = None

    def draw_progress(line: str):
        nonlocal last_draw_ts, last_draw_len
        now = time.time()
        if not line:
            return
        if (now - last_draw_ts) < draw_interval:
            return
        if ansi_supported:
            safe_write("\r\x1b[K" + line)
        else:
            pad = " " * max(0, last_draw_len - len(line))
            safe_write("\r" + line + pad)
        last_draw_len = len(line)
        last_draw_ts = now

    def clear_progress_line():
        nonlocal last_draw_len
        if last_draw_len == 0:
            return
        if ansi_supported:
            safe_write("\r\x1b[K")
        else:
            safe_write("\r" + " " * last_draw_len + "\r")
        last_draw_len = 0

    while True:
        ch = process.stdout.read(1)
        if not ch:
            break

        if ch in "\r\n":
            line = current_line.strip()

            if "MK/s" in line or "Average Speed" in line:
                speed_line = line
                draw_progress(speed_line)

            if "Range Finished!" in line:
                final_status_line = line

            if "Priv (HEX):" in line:
                pk_hex = line.split("Priv (HEX):")[-1].replace(" ", "").strip()
                if pk_hex.startswith("0x"):
                    pk_hex = pk_hex[2:]
                pk_hex = pk_hex.lower().zfill(64)
                if pk_hex not in found_keys:
                    found_keys.append(pk_hex)

            if "Public Addr:" in line:
                pub_addr = line.split("Public Addr:")[-1].strip()
                if pub_addr == TARGET_FIXED_ADDR:
                    target_result["pub_addr"] = pub_addr
                    missing_fields = {"Priv (WIF):": "priv_wif", "Priv (HEX):": "priv_hex"}
                    while missing_fields:
                        next_line = process.stdout.readline()
                        if not next_line:
                            break
                        for key in list(missing_fields.keys()):
                            if key in next_line:
                                if key == "Priv (WIF):":
                                    target_result[missing_fields[key]] = next_line.split(key)[-1].strip()
                                elif key == "Priv (HEX):":
                                    priv_hex = next_line.split(key)[-1].replace(" ", "").strip()
                                    if priv_hex.startswith("0x"):
                                        priv_hex = priv_hex[2:]
                                    target_result[missing_fields[key]] = priv_hex.lower().zfill(64)
                                missing_fields.pop(key)
                    found_target = True
                    clear_progress_line()
                    if speed_line:
                        print(speed_line)
                    scan_end_wall = now_str()
                    scan_elapsed = format_duration(time.perf_counter() - scan_start_perf)
                    try:
                        process.kill()
                    except Exception:
                        pass
                    break

            current_line = ""
        else:
            current_line += ch

        draw_progress(speed_line)

        if found_target:
            break

    process.wait()

    clear_progress_line()
    if final_status_line:
        print(final_status_line)
    scan_end_wall = now_str()
    scan_elapsed = format_duration(time.perf_counter() - scan_start_perf)
    print("【    结束时间    】：", scan_end_wall)
    print("【    本次耗时    】：", scan_elapsed)

    if os.path.exists(TEMP_ADDR_FILE):
        os.remove(TEMP_ADDR_FILE)
    return found_keys, found_target, target_result

# 如果找到私钥，将其保存至txt文件
def save_target_result(target_result):
    output_file = "71bit.txt"
    with open(output_file, "w") as f:
        f.write("Public Addr: " + target_result.get("pub_addr", "") + "\n")
    if target_result.get("priv_wif"):
        with open(output_file, "a") as f:
            f.write("Priv (WIF): " + target_result.get("priv_wif", "") + "\n")
    if target_result.get("priv_hex"):
        with open(output_file, "a") as f:
            f.write("Priv (HEX): " + target_result.get("priv_hex", "") + "\n")
    print("【私钥已保存至】：", "【" + output_file + "】")

# 主程序
def main():
    force_blocking_stdio()

    config = load_config()
    run_id = uuid.uuid4().hex[:4]
    config['run_id'] = run_id
    config['workername'] = f"{config['workername']}_{run_id}"
    print("【  当前显卡型号  】：", config.get("device_name"))

    if not os.path.exists(VANITYSEARCH_PATH):
        print(f"错误：未找到 {VANITYSEARCH_PATH} 文件，请确保该文件与程序在同一目录下！")
        sys.exit(1)

    while True:
        print("【  获取范围中... 】")
        range_data = get_range(config)
        if not range_data.get("success"):
            print("无法获取范围：", range_data.get("message"))
            sys.exit(1)
            continue
        range_value = range_data.get("range")
        addresses = range_data.get("addresses")
        server_worker = range_data.get("workername")
        if not range_value or not addresses:
            print("返回数据不完整，重新请求。")
            time.sleep(5)
            continue
        print(f"【    获得范围    】：  {range_value}")
        print("【 当前Worker名称 】：", server_worker)
        try:
            found_keys, found_target, target_result = run_vanitysearch(config, range_value, addresses)
        except Exception as e:
            print("\nvanitysearch发生错误，请重试。", e)
            break

        if found_target:
            save_target_result(target_result)
            print("【恭喜您找到了71位私钥！请在上述文件中查看私钥。】")
            print("【为了确保您安全转移奖励，强烈建议您使用Mara Pool提供的“Slipstream”服务，以确保在转移途中您的交易不会被脚本替换！（当然，这只是个建议。您无论通过何种方式转移奖励取决于您自己。）】")
            print("【如果您乐意，请考虑发送一些小费：bc1qkf8cqlngra48s994f5hczhe279ee74f6h8kgfn】")
            break

        if not found_keys:
            print("\nvanitysearch发生错误，请重试。")
            break

        proof_of_work = compute_sha256_sum(found_keys)
        submit_resp = submit_range_until_success(config, range_value, proof_of_work, config["device_name"], server_worker)
        if submit_resp.get("success"):
            print("范围提交成功。\n")
        else:
            print("\n范围提交失败，原因：", submit_resp.get("message"))
            time.sleep(60)
        time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n检测到 Ctrl+C，程序中断。")
    except Exception as e:
        print("程序出现异常：", e)
        traceback.print_exc()
    except SystemExit as se:
        print("程序中断。")
    print("按任意键退出。。。")
    getch()
    if os.name != "nt":
        os.system("stty sane")
