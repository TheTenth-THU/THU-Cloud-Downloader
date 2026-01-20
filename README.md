# Tsinghua Cloud Downloader

_Fork from [chenyifanthu/THU-Cloud-Downloader](https://github.com/chenyifanthu/THU-Cloud-Downloader)_

清华云盘批量下载助手，适用于分享的文件 size 过大导致无法直接下载的情况，本脚本添加了更多实用的小功能：

- [x] 直接下载链接中的所有文件，**无打包过程，无文件数量和大小限制**
- [x] 支持下载**带密码**云盘链接
- [x] 支持单个文件（f）链接和文件夹（d）链接
- [x] 显示文件下载总大小和下载进度
- [x] 支持**匹配选取**需要下载的文件（如指定文件类型/指定文件夹下载）
- [x] 自定义保存路径和自定义下载文件/文件夹名称
- [ ] 提供 `.hash.txt` 文件时，支持 Hash 校验下载文件完整性


## Dependency
需要提前安装 Python 3（开发使用 Python 3.8.10，更高版本应能兼容，安装过程略）以及 `requirements.txt` 文件里面的依赖库：
```shell
pip install -r requirements.txt
```

## Usage
|Flags|Default|Description|
|----|----|----|
|*--link*, *-l* |**Required** | 清华云盘分享链接。 Share link of Tsinghua Cloud. |
|*--save_dir*, *-s* | `~/Desktop` | 文件保存路径。缺省表示桌面路径。 Path to save the files. Default: Desktop |
|*--file*, *-f* | None | 正则匹配文件路径。缺省表示下载所有文件。 Regex to match the file path. Default: download all files.|
|*--password*, *-p* | None | 分享链接密码（如果需要）。 Password for the share link, if needed.|
|*--name*, *-n* | None | 自定义下载的单个文件名（针对单文件分享链接）或根目录名（针对目录分享链接）。缺省表示使用原始名称。 Custom name for the downloaded single file (for single-file share link) or the root directory (for directory share link). If not provided, the original name will be used. |
|*--hash*| False | 启用 Hash 校验下载文件完整性（需要分享链接中包含 `.hash.txt` 文件）。Enable hash check for downloaded files (requires a `.hash.txt` file in the share link). |

### Example
```shell
python thu_cloud_download.py \
    -l https://cloud.tsinghua.edu.cn/d/1234567890/ \
    -s "/PATH/TO/SAVE" \
    -f "*.pptx?" \              # 正则表达式 (if needed)
    -p "password" \             # (if needed)
    -n "custom_dir_name"        # (if needed)
```

### Support file format

*--file, -f* 参数使用 [`fnmatch` 标准库](https://docs.python.org/zh-cn/3.8/library/fnmatch.html)的 `fnmatch()` 进行文件名匹配，支持 UNIX shell 风格的通配符 pattern 字符串，支持使用如下几个通配符：

- **`*`** 可匹配任意个任意字符，**`?`** 可匹配一个任意字符。
    ```
    >>> import fnmatch
    >>> fnmatch.fnmatch('作业/part1', '作业/*')
    True
    >>> fnmatch.fnmatch('作业/part1', '作业/part?')
    True
    >>> fnmatch.fnmatch('作业/part12', '作业/part?')
    False
    ```
- **`[字符序列]`** 可匹配中括号里字符序列中的任意字符。该字符序列也支持中画线表示法，如 `[a-c]` 可代表 a、b、c 字符中任意一个。
    ```
    >>> import fnmatch
    >>> fnmatch.fnmatch('作业/part12', '作业/part[0-9][0-9]')
    True
    >>> fnmatch.fnmatch('作业/partA', '作业/part[0-9]')      
    False
    ```
- **`[!字符序列]`** 可匹配不在中括号里字符序列中的任意字符。
    ```
    >>> import fnmatch
    >>> fnmatch.fnmatch('作业/partA', '作业/part[!0-9]')
    True
    >>> fnmatch.fnmatch('作业/part1', '作业/part[!0-9]')
    False
    ```

注意，`fnmatch.fnmatch()` 函数**对大小写不敏感**。

*--file, -f* 参数的具体用法如下：
```shell
# 下载链接中所有文件
python thu_cloud_download.py -l https://share/link
# 下载链接中所有的 .txt 文件
python thu_cloud_download.py -l https://share/link -f *.txt
# 下载链接中某个文件夹的所有文件
python thu_cloud_download.py -l https://share/link -f folder/subfolder/*
``` 


## Output Log Example
```
PS> python .\thu_cloud_download.py -l https://cloud.tsinghua.edu.cn/d/d333****8446/ --hash
2026-01-21 02:10:37,965 - INFO - Share key: d333****8446
2026-01-21 02:10:37,965 - INFO - Share type: directory
2026-01-21 02:10:38,080 - INFO - Connected to the share link successfully.
2026-01-21 02:10:38,081 - INFO - Searching for files to be downloaded, Wait a moment...
====================================================================================================
Last Modified Time           File Size   File Path
----------------------------------------------------------------------------------------------------
2026-01-21T01:55:53+08:00    136.00 B    /.hash.txt
2025-01-20T23:11:56+08:00    157.89 MB   /VID_20250120_093654.mp4
2025-01-20T23:12:00+08:00    173.88 MB   /VID_20250120_093823.mp4
----------------------------------------------------------------------------------------------------
2026-01-21 02:10:38,133 - INFO - Num of File(s): 3. Total size:  331.8 MB.
Path to save the files (default: Desktop):
2026-01-21 02:10:39,010 - INFO - Root directory name: 第二组
2026-01-21 02:10:39,010 - INFO - Files will be saved into: E:\Files\Desktop\第二组
Input new name for the root dir, or press Enter to use original name: 
Start downloading? [y/N]y
2026-01-21 02:10:41,245 - WARNING - Save directory already exists. Files will be overwritten.
[3/3]: 100%|████████████████████████████████████████████████████| 332M/332M [00:05<00:00, 68.1MiB/s]
2026-01-21 02:10:46,387 - INFO - Download finished. Success: 2, Hash Mismatch: 0
```
