import os
from prompt_toolkit import prompt
from prompt_toolkit.completion import PathCompleter
import fnmatch
import platform     # Needed for OS check
if platform.system() == "Windows":
    import winreg

import re
import hashlib
import requests

import argparse
import urllib.parse
import logging
from tqdm import tqdm


sess = requests.Session()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def get_desktop_path() -> str:
    """Get the absolute path of the Desktop folder cross-platform."""
    if platform.system() == "Windows":
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r'Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders')
            desktop_path, _ = winreg.QueryValueEx(key, "Desktop")
            return desktop_path
        except Exception:
            logging.warning("Failed to get Desktop path from registry, falling back to standard path.")
    
    # Fallback for Linux/Mac or if registry fails
    return os.path.join(os.path.expanduser("~"), 'Desktop')


def parse_args():
    """Parse command line arguments.
    """
    usage = """
(to download files from a Tsinghua Cloud share link)
  python thu_cloud_download.py
  python thu_cloud_download.py -l LINK [-s SAVE_DIR] [-f FILE] [-p PASSWORD] [-n NAME] [--hash]
(to generate SHA1 hash for local files)
  python thu_cloud_download.py --hash -s PATH [-f FILE]"""
    epilog = """
examples:
  python thu_cloud_download.py
  python thu_cloud_download.py -l https://cloud.tsinghua.edu.cn/d/1234567890/ -s "~/path_to_save" -f "*.pptx?" -p "password" -n "custom_name"
  python thu_cloud_download.py --hash -s "~/path/to/files" -f \"*.txt\""""
    args = argparse.ArgumentParser(
        description='Download files from Tsinghua Cloud share link, or generate SHA1 hash for local files.',
        usage=usage,
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    args.add_argument('-l', '--link', type=str, required=False, help='Share link of Tsinghua Cloud')
    args.add_argument('-s', '--save_dir', type=str, default=None, help='Path to save the files. Default: Desktop')
    args.add_argument('-f', '--file', type=str, default=None, help='Regex to match the file path')
    args.add_argument('-p', '--password', type=str, default=None, help='Password for the share link')
    args.add_argument('-n', '--name', type=str, default=None, help='Custom name for the downloaded single file (for single-file share link) or the root directory (for directory share link). If not provided, the original name will be used.')
    args.add_argument('--hash', action='store_true', help='Verify integrity when downloading (with `-l`), or generate hash for local files (without `-l`)')
    return args.parse_args()


def get_share_key(url: str) -> str:
    """Get the share key from the share link.
    
    The share key lies in the link as `https://cloud.tsinghua.edu.cn/d/<share_key>/` 
    or `https://cloud.tsinghua.edu.cn/f/<share_key>/` format.
    """
    prefix = {'d': 'https://cloud.tsinghua.edu.cn/d/', 'f': 'https://cloud.tsinghua.edu.cn/f/'}
    if url.startswith(prefix['d']):
        share_type = 'd'
    elif url.startswith(prefix['f']):
        share_type = 'f'
    else:
        raise ValueError('Share link of Tsinghua Cloud should start with {}. URL {} not satisfied.'.format(prefix, url))
    share_key = url[len(prefix[share_type]):].replace('/', '')
    logging.info('Share key: {}'.format(share_key))
    logging.info('Share type: {}'.format('directory' if share_type == 'd' else 'file'))
    return share_key, share_type


def get_root_dir(share_key: str) -> str:
    """Get the root directory name from the share link.

    Run after `verify_password` function.
    """
    global sess
    pattern = '<meta property="og:title" content="(.*)" />'
    r = sess.get(f"https://cloud.tsinghua.edu.cn/d/{share_key}/")
    root_dir = re.findall(pattern, r.text)
    assert root_dir is not None, "Couldn't find title of the share link."
    logging.info("Root directory name: {}".format(root_dir[0]))
    return root_dir[0]


def verify_password(share_key: str, share_type: str, password: str) -> None:
    """Verify the password for the share link.
    
    Require password if the share link is password-protected,
    and verify the password provided by the user.
    """
    global sess
    r = sess.get(f"https://cloud.tsinghua.edu.cn/{share_type}/{share_key}/")
    if r.ok:
        logging.info("Connected to the share link successfully.")
    else:
        logging.error("Failed to connect to the share link.")
        return

    pattern = '<input type="hidden" name="csrfmiddlewaretoken" value="(.*)">'
    csrfmiddlewaretoken = re.findall(pattern, r.text)
    if csrfmiddlewaretoken:
        logging.info("This share link is password-protected.")
        if not password:
            pwd = input("Please enter the password: ")
        else:
            pwd = password

        csrfmiddlewaretoken = csrfmiddlewaretoken[0]
        data = {
            "csrfmiddlewaretoken": csrfmiddlewaretoken,
            "token": share_key,
            "password": pwd
        }
        r = sess.post(f"https://cloud.tsinghua.edu.cn/{share_type}/{share_key}/", data=data,
                    headers={"Referer": f"https://cloud.tsinghua.edu.cn/{share_type}/{share_key}/"})
        if "Please enter a correct password" in r.text:
            raise ValueError("Wrong password.")
        logging.info("Password verified successfully.")


def _is_match(file_path: str, pattern: str) -> bool:
    """Judge if the file path matches the regex provided by the user.
    """
    file_path = file_path[1:] # remove the first '/'
    return pattern is None or fnmatch.fnmatch(file_path, pattern)


def dfs_search_files(share_key: str, 
                     path: str = "/", 
                     pattern: str = None) -> list:
    """Search for files in the specified directory.

    Use `_is_match` function to judge if the path of a search result matches the regex provided by the user. 
    Search nested directories with DFS.
    """
    global sess
    filelist = []
    encoded_path = urllib.parse.quote(path)
    r = sess.get(f'https://cloud.tsinghua.edu.cn/api/v2.1/share-links/{share_key}/dirents/?path={encoded_path}')
    objects = r.json()['dirent_list']
    for obj in objects:
        if obj["is_dir"]:
            filelist.extend(
                dfs_search_files(share_key, obj['folder_path'], pattern))
        elif _is_match(obj["file_path"], pattern) or _is_match(obj["file_path"], '.hash.txt'):
            filelist.append(obj)
    return filelist


def download_single_file(url: str, fname: str, pbar: tqdm, 
                         expected_hash: str = None) -> bool:
    """Download a single file with streaming.
    """
    global sess
    resp = sess.get(url, stream=True)
    sha1 = hashlib.sha1() if expected_hash else None

    with open(fname, 'wb') as file:
        for data in resp.iter_content(chunk_size=1024):
            size = file.write(data)
            if sha1:
                sha1.update(data)
            pbar.update(size)

    if expected_hash:
        file_hash = sha1.hexdigest()
        if file_hash != expected_hash:
            logging.error(f"\nHash mismatch for file `{fname}`! Expected: {expected_hash}, Got: {file_hash}")
            return False
    return True

def print_filelist(share_type: str, filelist: list = None, fileinfo: dict = None) -> None:
    """Print a formatted table of the file list.
    """
    print("=" * 100)
    if share_type == 'd':
        print("Last Modified Time".ljust(25), " ", "File Size".rjust(10), " ", "File Path")
        print("-" * 100)
        for i, file in enumerate(filelist, 1):
            print(file["last_modified"], " ", _format_size(file["size"]).rjust(10), " ", file["file_path"])
            if i == 100:
                print("... %d more files" % (len(filelist) - 100))
                break
        print("-" * 100)
    elif share_type == 'f':
        print("File Name")
        print(fileinfo["fileName"])
        print("-" * 100)
        print("Shared By".ljust(30), "   ", "File Type".ljust(30), "   ", "File Size".rjust(30))
        # count CJK char in str(fileinfo["sharedBy"])
        cjk_count = sum(1 if _is_cjk(char) else 0 for char in str(fileinfo["sharedBy"]))
        print(str(fileinfo["sharedBy"]).ljust(30 - cjk_count), "   ", fileinfo["fileType"].ljust(30), "   ", _format_size(fileinfo["fileSize"]).rjust(30))
        print("-" * 100)

def _is_cjk(char: str) -> bool:
    if '\u4e00' <= char <= '\u9fff':
        return True
    else:
        return False

def _format_size(size: int) -> str:
    """Format file size in bytes to a human-readable string.
    """
    for unit in ['B ', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} PB"

def download_d(share_key: str, filelist: list, save_dir: str,
               check_hash: bool = False) -> None:
    """Download files in the list generated by `dfs_search_files`.

    Use `download_single_file` function to download each file. All downloaded files would be saved to the specified directory with their original names and structure.
    """
    if os.path.exists(save_dir):
        logging.warning("Save directory already exists. Files will be overwritten.")
    total_size = sum([file["size"] for file in filelist])
    pbar = tqdm(total=total_size, ncols=100, unit='iB', unit_scale=True, unit_divisor=1024)

    # find .hash.txt file and build hash dict
    hash_dict = {}
    for file in filelist:
        if file["file_path"].endswith('/.hash.txt'):
            hash_file_url = 'https://cloud.tsinghua.edu.cn/d/{}/files/?p={}&dl=1'.format(share_key, file["file_path"])
            hash_save_path = os.path.join(save_dir, file["file_path"][1:])
            pbar.set_description("[{}/{}]".format(1, len(filelist)))
            download_single_file(hash_file_url, hash_save_path, pbar)
            with open(hash_save_path, 'r') as f:
                for line in f:
                    parts = line.strip().split('  ')
                    if len(parts) == 2:
                        hash_dict[parts[1]] = parts[0]
            filelist.remove(file)
            break
    if check_hash and not hash_dict:
        logging.warning("No `.hash.txt` file found for integrity check.")
        check_hash = False

    success_count = 0
    fail_count = 0
    for i, file in enumerate(filelist):
        file_url = 'https://cloud.tsinghua.edu.cn/d/{}/files/?p={}&dl=1'.format(share_key, file["file_path"])
        save_path = os.path.join(save_dir, file["file_path"][1:])
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        # logging.info("[{}/{}] Downloading File: {}".format(i + 1, len(filelist), save_path))
        expected_hash = hash_dict.get(file["file_path"]) if check_hash else None

        try:
            pbar.set_description("[{}/{}]".format(
                i + 1 if not check_hash else i + 2,     # skip .hash.txt file
                len(filelist) if not check_hash else len(filelist) + 1
            ))
            if download_single_file(file_url, save_path, pbar, expected_hash=expected_hash):
                success_count += 1
            else:
                fail_count += 1
            
        except Exception as e:
            logging.error("Error happened when downloading file: {}".format(save_path))
            logging.error(e)

    pbar.close()
    if check_hash:
        logging.info(f"Download finished. Success: {success_count}, Hash Mismatch: {fail_count}")
    else:
        logging.info(f"Download finished.")


def download_f(share_key: str, save_path: str, total_size: int) -> None:
    """Download file from a single-file share link.

    Use `download_single_file` function to download the file into the specified path. `save_path` has already included the original name of the file.
    """
    if os.path.exists(save_path):
        logging.warning("Save directory already exists. Files will be overwritten.")
    pbar = tqdm(total=total_size, ncols=100, unit='iB', unit_scale=True, unit_divisor=1024)
    file_url = f'https://cloud.tsinghua.edu.cn/f/{share_key}/?dl=1'

    try:
        download_single_file(file_url, save_path, pbar)
    except Exception as e:
        logging.error("Error happened when downloading file: {}".format(save_path))
        logging.error(e)
    pbar.close()
    logging.info("Download finished.")


def get_single_file_info(share_key: str) -> list:
    global sess
    r = sess.get(f'https://cloud.tsinghua.edu.cn/f/{share_key}/')
    if not r.ok:
        logging.error("Failed to connect to the share link for the file info.")
        return
    logging.debug(r.text)

    pattern = 'window.shared = {([\s\S]*)};'
    r = re.findall(pattern, r.text)
    info_keys = ['sharedBy', 'fileName', 'fileSize', 'fileType']
    info = {}
    for key in info_keys:
        value = re.findall(f"{key}: '(.*?)',", r[0])
        if not value:
            # for non-str data
            value = re.findall(f'{key}: (.*?),', r[0])
        info[key] = value[0] if value else None
    return info

def generate_file_hash(path: str, pattern: str = None) -> None:
    """ Generate SHA1 hash for local files matching the regex.
    """
    if not os.path.exists(path):
        logging.error(f"Path {path} does not exist.")
        return
    
    if os.path.isfile(path):
        # for single file
        files_to_hash = [os.path.basename(path)]
        save_dir = os.path.abspath(os.path.dirname(path))
    elif os.path.isdir(path):
        # for directory
        files_to_hash = []
        for root, _, files in os.walk(path):
            for file in files:
                file_path = os.path.join(root, file)
                rel_path = '/' + os.path.relpath(file_path, path)
                if _is_match(rel_path, pattern):
                    files_to_hash.append(rel_path)
        save_dir = os.path.abspath(path)
    else:
        logging.error(f"Path {path} is neither a file nor a directory.")
        return
    
    hash_pairs = []
    for path_to_hash in files_to_hash:
        sha1 = hashlib.sha1()
        with open(os.path.join(save_dir, path_to_hash[1:]), 'rb') as f:
            while True:
                data = f.read(1024)
                if not data:
                    break
                sha1.update(data)
        file_hash = sha1.hexdigest()
        logging.info(f"{file_hash}  {path_to_hash}")
        hash_pairs.append((path_to_hash, file_hash))
    
    # write to file
    hash_file = os.path.join(save_dir, '.hash.txt')
    if os.path.exists(hash_file):
        logging.warning(f"Hash file `{hash_file}` already exists and will be backed up at `{hash_file}.bak` before being overwritten.")
        os.rename(hash_file, hash_file + '.bak')
    with open(hash_file, 'w') as f:
        for path_to_hash, file_hash in hash_pairs:
            f.write(f"{file_hash}  {path_to_hash}\n")


def main():
    args = parse_args()
    url, pattern, save_dir, password, name, to_hash = args.link, args.file, args.save_dir, args.password, args.name, args.hash

    if not url and to_hash:
        # Generate hash for local files
        if not save_dir:
            logging.warning("To generate hash for local files, a valid path should be provided by `-s` or `--save_dir` to specify files.")
            save_dir = prompt("File or directory: ", completer=PathCompleter())
            if not save_dir:
                return
        generate_file_hash(save_dir, pattern=pattern)
        return
    elif not url:
        logging.warning("To download files, a valid share link should be provided by `-l` or `--link`.")
        url = input("Share link of Tsinghua Cloud: ")
        save_dir = prompt("Path to save the files (default: Desktop): ", completer=PathCompleter()) or None

    share_key, share_type = get_share_key(url)
    verify_password(share_key, share_type, password)
    
    if share_type == 'd':
        # search files
        logging.info("Searching for files to be downloaded, Wait a moment...")
        filelist = dfs_search_files(share_key, pattern=pattern)
        filelist.sort(key=lambda x: x["file_path"])
        if not filelist:
            logging.info("No file found.")
            return

        print_filelist(share_type, filelist=filelist)
        total_size = sum([file["size"] for file in filelist]) / 1024 / 1024 # MB
        logging.info(f"Num of File(s): {len(filelist)}. Total size: {total_size: .1f} MB.")
    
        # Save to desktop by default.
        if save_dir is None:
            save_dir = prompt("Path to save the files (default: Desktop): ", completer=PathCompleter()) or None
        if save_dir is None:
            save_dir = get_desktop_path()
            assert os.path.exists(save_dir), f"`{save_dir}` folder not found."
        root_dir = get_root_dir(share_key)
        save_dir = os.path.join(save_dir, name if name else root_dir)
        logging.info(f"Files will be saved into: {save_dir}")
        rename = input("Input new name for the root dir, or press Enter to use original name: ")
        if rename:
            save_dir = os.path.join(os.path.dirname(save_dir), rename)
            logging.info(f"Files will be saved into: {save_dir}")
        
        key = input("Start downloading? [y/N] ")
        if key != 'y' and key != 'Y':
            return
        download_d(share_key, filelist, save_dir, check_hash=to_hash)
    
    if share_type == 'f':
        if pattern:
            logging.warning("Regex {} is ignored when downloading a single file.".format(pattern))
        logging.info("Searching for the file to be downloaded, Wait a moment...")
        info = get_single_file_info(share_key)

        print_filelist(share_type, fileinfo=info)
        total_size = int(info["fileSize"]) / 1024 / 1024 # MB
        logging.info(f"Total size: {total_size: .1f} MB.")
        
        # Save to desktop by default.
        if save_dir is None:
            save_dir = prompt("Path to save the file (default: Desktop): ", completer=PathCompleter()) or None
        if save_dir is None:
            save_dir = get_desktop_path()
            assert os.path.exists(save_dir), f"`{save_dir}` folder not found."
        elif not os.path.exists(save_dir):
            os.makedirs(save_dir)
        logging.info(f"The file will be saved as: {os.path.join(save_dir, name if name else info['fileName'])}")
        rename = input("Input new name for the file, or press Enter to use original name: ")
        if rename:
            name = rename
            logging.info(f"The file will be saved as: {os.path.join(save_dir, name)}")
        
        key = input("Start downloading? [y/N] ")
        if key != 'y' and key != 'Y':
            return
        download_f(share_key, os.path.join(save_dir, name if name else info["fileName"]), int(info["fileSize"]))

    
if __name__ == '__main__':
    """
    用法:
    python thu_cloud_download.py \
    -l https://cloud.tsinghua.edu.cn/d/1234567890/ \
    -s "~/path_to_save" \
    -f "*.pptx?" (regex, 正则表达式) \
    -p "password" \
    -n "custom_name" \
    --hash
    """
    main()
