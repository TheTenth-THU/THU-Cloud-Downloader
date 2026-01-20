from ast import arg
import os
import re
import logging
import fnmatch
import requests
import argparse
import urllib.parse
from tqdm import tqdm


sess = requests.Session()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def parse_args():
    """Parse command line arguments.
    """
    args = argparse.ArgumentParser()
    args.add_argument('-l', '--link', type=str, required=True, help='Share link of Tsinghua Cloud')
    args.add_argument('-s', '--save_dir', type=str, default=None, help='Path to save the files. Default: Desktop')
    args.add_argument('-f', '--file', type=str, default=None, help='Regex to match the file path')
    args.add_argument('-p', '--password', type=str, default=None, help='Password for the share link')
    args.add_argument('-n', '--name', type=str, default=None, help='Custom name for the downloaded single file (for single-file share link) or the root directory (for directory share link). If not provided, the original name will be used.')
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


def is_match(file_path: str, pattern: str) -> bool:
    """Judge if the file path matches the regex provided by the user.
    """
    file_path = file_path[1:] # remove the first '/'
    return pattern is None or fnmatch.fnmatch(file_path, pattern)


def dfs_search_files(share_key: str, 
                     path: str = "/", 
                     pattern: str = None) -> list:
    """Search for files in the specified directory.

    Use `is_match` function to judge if the path of a search result matches the regex provided by the user. 
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
        elif is_match(obj["file_path"], pattern):
            filelist.append(obj)
    return filelist


def download_single_file(url: str, fname: str, pbar: tqdm):
    """Download a single file with streaming.
    """
    global sess
    resp = sess.get(url, stream=True)
    with open(fname, 'wb') as file:
        for data in resp.iter_content(chunk_size=1024):
            size = file.write(data)
            pbar.update(size)


def print_filelist(share_type: str, filelist: list = None, fileinfo: dict = None) -> None:
    """Print a formatted table of the file list.
    """
    print("=" * 100)
    if share_type == 'd':
        print("Last Modified Time".ljust(25), " ", "File Size".rjust(10), " ", "File Path")
        print("-" * 100)
        for i, file in enumerate(filelist, 1):
            print(file["last_modified"], " ", str(file["size"]).rjust(10), " ", file["file_path"])
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
        print(str(fileinfo["sharedBy"]).ljust(30 - cjk_count), "   ", fileinfo["fileType"].ljust(30), "   ", str(fileinfo["fileSize"]).rjust(30))
        print("-" * 100)

def _is_cjk(char: str) -> bool:
    if '\u4e00' <= char <= '\u9fff':
        return True
    else:
        return False

def download_d(share_key: str, filelist: list, save_dir: str) -> None:
    """Download files in the list generated by `dfs_search_files`.

    Use `download_single_file` function to download each file. All downloaded files would be saved to the specified directory with their original names and structure.
    """
    if os.path.exists(save_dir):
        logging.warning("Save directory already exists. Files will be overwritten.")
    total_size = sum([file["size"] for file in filelist])
    pbar = tqdm(total=total_size, ncols=100, unit='iB', unit_scale=True, unit_divisor=1024)
    for i, file in enumerate(filelist):
        file_url = 'https://cloud.tsinghua.edu.cn/d/{}/files/?p={}&dl=1'.format(share_key, file["file_path"])
        save_path = os.path.join(save_dir, file["file_path"][1:])
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        # logging.info("[{}/{}] Downloading File: {}".format(i + 1, len(filelist), save_path))
        try:
            pbar.set_description("[{}/{}]".format(i + 1, len(filelist)))
            download_single_file(file_url, save_path, pbar)
            
        except Exception as e:
            logging.error("Error happened when downloading file: {}".format(save_path))
            logging.error(e)
    pbar.close()
    logging.info("Download finished.")


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

def main():
    args = parse_args()
    url, pattern, save_dir, password, name = args.link, args.file, args.save_dir, args.password, args.name
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
            save_dir = os.path.join(os.path.expanduser("~"), 'Desktop')
            assert os.path.exists(save_dir), "Desktop folder not found."
        root_dir = get_root_dir(share_key)
        save_dir = os.path.join(save_dir, name if name else root_dir)
        logging.info(f"Files will be saved into: {save_dir}")
        rename = input("Input new name for the root dir, or press Enter to use original name:")
        if rename:
            save_dir = os.path.join(os.path.dirname(save_dir), rename)
            logging.info(f"Files will be saved into: {save_dir}")
        
        key = input("Start downloading? [y/N]")
        if key != 'y' and key != 'Y':
            return
        download_d(share_key, filelist, save_dir)
    
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
            save_dir = os.path.join(os.path.expanduser("~"), 'Desktop')
            assert os.path.exists(save_dir), "Desktop folder not found."
        elif not os.path.exists(save_dir):
            os.makedirs(save_dir)
        logging.info(f"The file will be saved as: {os.path.join(save_dir, name if name else info['fileName'])}")
        rename = input("Input new name for the file, or press Enter to use original name:")
        if rename:
            name = rename
            logging.info(f"The file will be saved as: {os.path.join(save_dir, name)}")
        
        key = input("Start downloading? [y/N]")
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
    -n "custom_name"
    """
    main()
