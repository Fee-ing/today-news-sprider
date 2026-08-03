# main.py

import requests
import urllib.parse
import base64
from bs4 import BeautifulSoup
import os
import json
from dotenv import load_dotenv
from datetime import datetime
try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except ImportError:
    from backports.zoneinfo import ZoneInfo  # Python < 3.9


URL = "https://tophub.today/"


load_dotenv()

GH_PAT = os.environ.get("GH_PAT")
GH_REPO = os.environ.get("GH_REPO")


def crawl_data():
  headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
  }

  try:
    response = requests.get(URL, headers=headers, timeout=15)
    response.raise_for_status()  # 如果状态码不是200，会抛出异常

    soup = BeautifulSoup(response.text, "html.parser")

    # --- 重要：请在这里编写你具体的解析逻辑 ---
    # 示例：获取某个特定元素，如一个新闻列表的第一条新闻
    result = []
    for block in soup.select("div.bc-cc > div.cc-cd"):
      try:
        source_el = block.select_one("div.cc-cd-ih a div.cc-cd-lb > span")
        if not source_el:
          print(f"警告: 未找到 source 元素，跳过本块")
          continue
        source = source_el.text.strip().replace(" ", "")

        type_el = block.parent.find_previous_sibling(class_='bc-tc')
        if type_el:
          type_str = type_el.text.strip().replace(" ", "")
        else:
          type_str = "未知分类"

        content = []
        for item in block.select("div.cc-cd-cb a"):
          try:
            text_el = item.find("span", class_="t")
            heat_el = item.find("span", class_="e")
            content.append(
              {
                "url": item.get("href", ""),
                "text": text_el.text.strip() if text_el else "",
                "heat": heat_el.text.strip() if heat_el else "",
              }
            )
          except Exception as e:
            print(f"解析单条内容出错: {e}")
        result.append({"source": source, "type": type_str, "content": content})
      except Exception as e:
        print(f"解析单个 block 出错: {e}")
        continue

    if not result:
      print("解析完成但结果为空，可能是页面结构已变化。")
      print("页面标题:", soup.title.string if soup.title else "无标题")
    return result

  except requests.exceptions.RequestException as e:
    print(f"网络请求失败: {e}")
    return None
  except Exception as e:
    import traceback
    print(f"解析页面时发生错误: {e}")
    traceback.print_exc()
    return None


def save_news_json(data_list, filepath="news.json"):
    """将爬取数据保存为本地 JSON 文件，返回格式化后的数据"""
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    timestamp = int(now.timestamp())

    json_data = {
        "timestamp": timestamp,
        "events": data_list,
    }

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)

    print(f"JSON 文件已保存：{filepath}")
    return json_data


def push_to_github_pages(json_data, filepath="news.json"):
    """将 news.json 推送到 GitHub 仓库的 master 分支"""
    if not all([GH_PAT, GH_REPO]):
        print("错误：环境变量 GH_PAT, GH_REPO 未设置完整。跳过推送。")
        return False

    headers = {
        "Authorization": f"token {GH_PAT}",
        "Accept": "application/vnd.github.v3+json"
    }

    # 检查 master 分支是否存在
    branch_ref_url = f"https://api.github.com/repos/{GH_REPO}/git/refs/heads/master"
    branch_exists = False
    try:
        ref_response = requests.get(branch_ref_url, headers=headers)
        if ref_response.status_code == 200:
            branch_exists = True
            print("master 分支已存在")
        elif ref_response.status_code == 404:
            print("master 分支不存在，将自动创建")
        else:
            print(f"检查分支异常：{ref_response.status_code} {ref_response.text}")
    except Exception as e:
        print(f"检查分支异常：{e}")

    # 如果分支不存在，从默认分支创建 master
    if not branch_exists:
        try:
            # 获取仓库信息（默认分支名）
            repo_url = f"https://api.github.com/repos/{GH_REPO}"
            repo_response = requests.get(repo_url, headers=headers)
            if repo_response.status_code != 200:
                print(f"获取仓库信息失败：{repo_response.status_code} {repo_response.text}")
                return False
            default_branch = repo_response.json().get("default_branch", "main")

            # 获取默认分支最新 commit SHA
            ref_default_url = f"https://api.github.com/repos/{GH_REPO}/git/refs/heads/{default_branch}"
            ref_default_response = requests.get(ref_default_url, headers=headers)
            if ref_default_response.status_code != 200:
                print(f"获取默认分支失败：{ref_default_response.status_code}")
                return False
            base_sha = ref_default_response.json()["object"]["sha"]

            # 创建 master 分支
            create_branch_payload = {
                "ref": "refs/heads/master",
                "sha": base_sha
            }
            create_response = requests.post(
                f"https://api.github.com/repos/{GH_REPO}/git/refs",
                headers=headers,
                json=create_branch_payload
            )
            if create_response.status_code == 201:
                print("master 分支创建成功")
            else:
                print(f"创建分支失败：{create_response.status_code} {create_response.json()}")
                return False
        except Exception as e:
            print(f"创建分支异常：{e}")
            return False

    FILE_PATH = f"JSONs/{filepath}"  # 确保写入子目录
    api_url = f"https://api.github.com/repos/{GH_REPO}/contents/{urllib.parse.quote(FILE_PATH, safe='/')}"

    content = json.dumps(json_data, ensure_ascii=False, indent=2)
    content_bytes = content.encode('utf-8')
    content_base64 = base64.b64encode(content_bytes).decode('utf-8')

    # 检查 master 分支上是否已存在该文件
    sha = None
    try:
        response = requests.get(f"{api_url}?ref=master", headers=headers)
        if response.status_code == 200:
            sha = response.json().get("sha")
            print(f"文件已存在，将更新（SHA: {sha[:7]}...）")
        elif response.status_code == 404:
            print("文件不存在，将创建新文件")
        else:
            print(f"检查文件状态异常：{response.status_code} {response.text}")
    except Exception as e:
        print(f"检查文件异常：{e}")

    # 创建或更新文件
    commit_message = f"Update news.json - {json_data.get('date', '')}"
    payload = {
        "message": commit_message,
        "content": content_base64,
        "branch": "master"
    }
    if sha:
        payload["sha"] = sha

    try:
        response = requests.put(api_url, headers=headers, json=payload)
        if response.status_code in (200, 201):
            print(f"✓ news.json 推送成功 → https://github.com/{GH_REPO}/blob/master/{filepath}")
            return True
        else:
            print(f"推送失败：{response.status_code} {response.json()}")
            return False
    except Exception as e:
        print(f"推送异常：{e}")
        return False


if __name__ == "__main__":
  print("开始爬取数据...")
  data = crawl_data()

  if data:
    print("数据爬取成功")

    json_data = save_news_json(data)
    push_to_github_pages(json_data)
  else:
    print("数据爬取失败")
