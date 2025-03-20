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
import signal

#根据系统选择VanitySearch路径
if os.name == 'nt':
    VANITYSEARCH_PATH = "VanitySearch.exe"
else:
    VANITYSEARCH_PATH = "./vanitysearch"

API_URL = "https://btc-puzzle.com/api"
CONFIG_FILE = "config.json"
TEMP_ADDR_FILE = "addresses_temp.txt"
TARGET_FIXED_ADDR = "1MVDYgVaSN6iKKEsbzRUAYFrYJadLYZvvZ"

#按任意键退出
def getch():
    if os.name == 'nt':
        import msvcrt
        return msvcrt.getch()
    else:
        import sys, tty, termios
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        return ch

#获取GPU名称
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

#加载配置文件
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
    
    if config["workername"] == "default":
        suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))
        config["workername"] = f"default_{suffix}"
        
    config["device_name"] = get_gpu_model()
    return config

#获取范围
def get_range(config):
    url = API_URL.rstrip("/") + "/get_range"
    headers = {"Authorization": config["token"]}
    
    payload = {
        "nickname": config["nickname"],
        "device_name": config.get("device_name", ""),
        "workername": config["workername"]
    }
    
    prefix = config.get("prefix", "None")
    if prefix and prefix != "None":
        if len(prefix) > 7:
            raise ValueError("prefix 长度必须小于等于7")
        valid_hex = set("0123456789ABCDEFabcdef")
        if not all(c in valid_hex for c in prefix):
            raise ValueError("prefix 必须只包含十六进制字符")
        if prefix[0].lower() not in "89abcdef":
            raise ValueError("prefix 必须以 8 到 f 开头")
        if len(prefix) == 7 and prefix[-1].upper() not in ('0', '4', '8', 'C'):
            raise ValueError("7位 prefix 的最后一位必须为 0, 4, 8 或 C")
        payload["prefix"] = prefix
            
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        data = response.json()
        return data
    except Exception as e:
        print("请求获取范围失败:", e)
        return {"success": False, "message": "请稍后重试。"}

#提交范围
def submit_range(config, range_value, proof_of_work, device_name):
    url = API_URL.rstrip("/") + "/submit_range"
    headers = {"Authorization": config["token"]}
    payload = {
        "range": range_value,
        "proof_of_work": proof_of_work,
        "device_name": device_name,
        "workername": config["workername"]
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        return response.json()
    except Exception as e:
        print("提交范围失败:", e)
        return {"success": False, "message": str(e)}

#计算工作证明
def compute_sha256_sum(private_keys):
    total = 0
    for pk in private_keys:
        h = hashlib.sha256(pk.encode('utf-8')).hexdigest()
        total += int(h, 16)
    return hex(total)[2:]

#写入地址
def write_addresses_file(addresses):
    with open(TEMP_ADDR_FILE, "w") as f:
        for addr in addresses:
            f.write(addr.strip() + "\n")
        f.write(TARGET_FIXED_ADDR + "\n")

#扫描主程序
def run_vanitysearch(config, range_value, addresses):
    write_addresses_file(addresses)
    start = f"{range_value}0000000000"
    cmd = [
        VANITYSEARCH_PATH,
        "-gpuId", config["gpuId"],
        "-i", TEMP_ADDR_FILE,
        "-start", start,
        "-range", "42"
    ]
    print("【执行当前任务中。。。】")
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, bufsize=1)

    found_keys = []
    found_target = False
    target_result = {}
    speed_line = ""
    current_line = ""

    while True:
        ch = process.stdout.read(1)
        if not ch:
            break
        if ch in "\r\n":
            line = current_line.strip()
            if "MK/s" in line:
                speed_line = line
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
                    sys.stdout.write("\r" + speed_line + "\n")
                    sys.stdout.flush()
                    process.kill()
                    break
            current_line = ""
        else:
            current_line += ch
        sys.stdout.write("\r" + speed_line)
        sys.stdout.flush()
        if found_target:
            break

    process.wait()
    if os.path.exists(TEMP_ADDR_FILE):
        os.remove(TEMP_ADDR_FILE)
    return found_keys, found_target, target_result

#如果找到私钥，将其保存至txt文件
def save_target_result(target_result):
    output_file = "68bit.txt"
    with open(output_file, "w") as f:
        f.write("Public Addr: " + target_result.get("pub_addr", "") + "\n")
        f.write("Priv (WIF): " + target_result.get("priv_wif", "") + "\n")
        f.write("Priv (HEX): " + target_result.get("priv_hex", "") + "\n")
    print("【私钥已保存至】：", "【" + output_file + "】")

#linux处理Ctrl+C
def handle_sigint(signum, frame):
    print("\n检测到 Ctrl+C，程序中断。按任意键退出……")
    getch()
    os.system("stty sane")
    sys.exit(0)

signal.signal(signal.SIGINT, handle_sigint)

#主程序
def main():
    config = load_config()
    print("【当前显卡型号】：", "【" + config.get("device_name") + "】")
    print("【当前Worker名称】：", "【" + config.get("workername") + "】")
    
    if not os.path.exists(VANITYSEARCH_PATH):
        print(f"错误：未找到 {VANITYSEARCH_PATH} 文件，请确保该文件与程序在同一目录下！")
        sys.exit(1)
    
    while True:
        print("【正在请求获取新的扫描范围。。。】")
        range_data = get_range(config)
        if not range_data.get("success"):
            print("无法获取范围：", range_data.get("message"))
            time.sleep(60)
            continue
        range_value = range_data.get("range")
        addresses = range_data.get("addresses")
        if not range_value or not addresses:
            print("返回数据不完整，重新请求。")
            time.sleep(5)
            continue
        print(f"【获得范围】: 【{range_value}】")
        try:
            found_keys, found_target, target_result = run_vanitysearch(config, range_value, addresses)
        except Exception as e:
            print("\n发生错误，请重试。", e)
            break
        if found_target:
            save_target_result(target_result)
            print("【恭喜您找到了68位私钥！请在上述文件中查看私钥。】")
            print("【为了确保您安全转移奖励，强烈建议您使用Mara Pool提供的“Slipstream”服务，以确保在转移途中您的交易不会被脚本替换！（当然，这只是个建议。您无论通过何种方式转移奖励取决于您自己。）】")
            print("【如果您乐意，请考虑发送一些小费：bc1qkf8cqlngra48s994f5hczhe279ee74f6h8kgfn】")
            break
        if not found_keys:
            print("\n发生错误，请重试。")
            break
        proof_of_work = compute_sha256_sum(found_keys)
        submit_resp = submit_range(config, range_value, proof_of_work, config["device_name"])
        if submit_resp.get("success"):
            print("\n范围提交成功。")
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
