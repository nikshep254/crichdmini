
import re
import subprocess
import logging
import datetime

# Fallback for ZoneInfo for older Python versions
try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

# --- Configuration ---
CRICHD_BASE_URL = "https://crichd.com.co"
PLAYER_DOMAIN_PATTERN = r"https://(?:player\.)?dadocric\.st/player\.php"
PLAYERADO_EMBED_URL = "https://playerado.top/embed2.php"
ATPLAY_URL = "https://player0003.com/atplay.php"
OUTPUT_M3U_FILE = "siamscrichd.m3u"
EPG_URL = "https://github.com/epgshare01/share/raw/master/epg_ripper_ALL_SOURCES1.xml.gz"

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def run_command(command):
    logging.info(f"Running command: {command}")
    result = subprocess.run(command, capture_output=True, text=True, shell=True)
    if result.returncode != 0:
        logging.error(f"Command failed with exit code {result.returncode}")
        logging.error(f"Stderr: {result.stderr}")
    return result.stdout

def get_channel_links():
    logging.info(f"Fetching channel links from {CRICHD_BASE_URL}")
    main_page_content = run_command(f"curl -L {CRICHD_BASE_URL}")
    if not main_page_content:
        logging.error("Failed to fetch CricHD homepage")
        return []
    pattern = r'<li class="has-sub"><a href="(' + re.escape(CRICHD_BASE_URL) + r'/channels/[^"]+)"'
    channel_links = re.findall(pattern, main_page_content)
    logging.info(f"Found {len(channel_links)} channel links")
    return channel_links

def get_stream_link(channel_url):
    logging.info(f"Fetching stream link for {channel_url}")
    channel_page_content = run_command(f"curl -L {channel_url}")
    if not channel_page_content:
        logging.error(f"Failed to fetch channel page: {channel_url}")
        return None, None, None

    pattern_string = r"<a[^>]+href=['\"](" + PLAYER_DOMAIN_PATTERN + r"\?id=[^\'\"]+)['\"]"
    player_link_match = re.search(pattern_string, channel_page_content)

    if not player_link_match:
        logging.warning(f"Player link not found on {channel_url}")
        return None, None, None

    player_link = player_link_match.group(1)
    player_id = player_link.split("id=")[1]
    playerado_url = f"{PLAYERADO_EMBED_URL}?id={player_id}"
    logging.info(f"Fetching embed page: {playerado_url}")
    
    embed_page_content = run_command(f"curl -L '{playerado_url}'")
    if not embed_page_content:
        logging.error(f"Failed to fetch embed page: {playerado_url}")
        return None, None, None

    fid_match = re.search(r'fid\s*=\s*"([^"]+)"', embed_page_content)
    v_con_match = re.search(r'v_con\s*=\s*"([^"]+)"', embed_page_content)
    v_dt_match = re.search(r'v_dt\s*=\s*"([^"]+)"', embed_page_content)

    if not (fid_match and v_con_match and v_dt_match):
        logging.warning(f"Could not find all required variables on {playerado_url}")
        return None, None, None

    fid = fid_match.group(1)
    v_con = v_con_match.group(1)
    v_dt = v_dt_match.group(1)

    atplay_url = f"{ATPLAY_URL}?v={fid}&hello={v_con}&expires={v_dt}"
    logging.info(f"Fetching atplay page: {atplay_url}")

    atplay_page_content = run_command(f"curl -iL --user-agent \"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36\" --referer \"https://playerado.top/\" '{atplay_url}'")
    if not atplay_page_content:
        logging.error(f"Failed to fetch atplay page: {atplay_url}")
        return None, None, None

    func_name_match = re.search(r'player\.load\({source: (\w+)\(\),', atplay_page_content)
    if not func_name_match:
        logging.warning(f"Could not find player.load function in {atplay_url}")
        return None, None, None
    func_name = func_name_match.group(1)
    logging.info(f"Found player function: {func_name}")

    func_def_pattern = r'function\s+' + func_name + r'\s*\(\)\s*\{(.*?)\}'
    func_def_match = re.search(func_def_pattern, atplay_page_content, re.DOTALL)
    if not func_def_match:
        logging.warning(f"Could not find function definition for {func_name} in {atplay_url}")
        return None, None, None
    func_body = func_def_match.group(1)

    base_url_var_match = re.search(r'var url = (\w+);', func_body)
    md5_var_match = re.search(r'url \+= "\?md5="\s*\+\s*(\w+);', func_body)
    expires_var_match = re.search(r'url \+= "&expires="\s*\+\s*(\w+);', func_body)
    s_var_match = re.search(r'url \+= "&s="\s*\+\s*(\w+);', func_body)

    if not (base_url_var_match and md5_var_match and expires_var_match and s_var_match):
        logging.warning("Could not find all parameter vars in function body")
        return None, None, None

    base_url_var = base_url_var_match.group(1)
    md5_var = md5_var_match.group(1)
    expires_var = expires_var_match.group(1)
    s_var = s_var_match.group(1)

    md5_val_match = re.search(r'var ' + md5_var + r'\s*=\s*"(.*?)"', atplay_page_content)
    expires_val_match = re.search(r'var ' + expires_var + r'\s*=\s*"(.*?)"', atplay_page_content)
    s_val_match = re.search(r'var ' + s_var + r'\s*=\s*"(.*?)"', atplay_page_content)

    if not (md5_val_match and expires_val_match and s_val_match):
        logging.warning(f"Could not find values for all parameters in {atplay_url}")
        return None, None, None

    md5 = md5_val_match.group(1)
    expires = expires_val_match.group(1)
    s_val = s_val_match.group(1)

    base_url_constructor_match = re.search(r'var ' + base_url_var + r'\s*=\s*(.*?);', atplay_page_content)
    if not base_url_constructor_match:
        logging.warning(f"Could not find constructor for base url var {base_url_var}")
        return None, None, None
        
    constructor_string = base_url_constructor_match.group(1)
    real_base_url_var = constructor_string.split('+')[0].strip()
    
    real_base_url_match = re.search(r"var " + real_base_url_var + r" = (.*?);", atplay_page_content)
    if not real_base_url_match:
        logging.warning(f"Could not find definition for real base url var {real_base_url_var}")
        return None, None, None
        
    base_url_str_with_plus = real_base_url_match.group(1)
    js_string_parts = re.findall(r"'(.*?)'", base_url_str_with_plus)
    base_url = "".join(js_string_parts)
    
    v_param = fid
    stream_path = f"/hls/{v_param}.m3u8"
    final_stream_link = f"{base_url}{stream_path}?md5={md5}&expires={expires}&ch={v_param}&s={s_val}"
    
    channel_name_match = re.search(r'<title>(.*?)</title>', channel_page_content)
    channel_name = channel_name_match.group(1).split(" Live Streaming")[0] if channel_name_match else "Unknown Channel"

    logging.info(f"Successfully extracted stream for {channel_name}: {final_stream_link}")
    return channel_name, final_stream_link, "https://player0003.com/"


if __name__ == "__main__":
    channel_links = get_channel_links()
    
    channels_data = []
    for link in channel_links:
        name, stream, referrer = get_stream_link(link)
        if name and stream:
            channels_data.append((name, stream, referrer))

    total_channels = len(channels_data)
    if ZoneInfo:
        dhaka_tz = ZoneInfo('Asia/Dhaka')
        update_time = datetime.datetime.now(dhaka_tz).strftime('%Y-%m-%d %I:%M:%S %p')
    else: # Fallback for older python
        update_time = datetime.datetime.now().strftime('%Y-%m-%d %I:%M:%S %p') + " UTC"

    with open(OUTPUT_M3U_FILE, "w", encoding='utf-8') as f:
        f.write(f'#EXTM3U x-tvg-url="{EPG_URL}"\n')
        f.write(f'# Made by Siam3310\n')
        f.write(f'# Last updated: {update_time} (Bangladesh/Dhaka)\n')
        f.write(f'# Total channels: {total_channels}\n\n')
        for name, stream, referrer in channels_data:
            f.write(f'#EXTINF:-1 tvg-name="{name}",{name}\n')
            f.write(f"#EXTVLCOPT:http-referrer={referrer}\n")
            f.write(f"{stream}\n")
