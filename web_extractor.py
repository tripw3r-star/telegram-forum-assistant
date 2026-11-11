import re
import httpx
from bs4 import BeautifulSoup
from typing import Optional, Dict, List
import urllib.parse

URL_REGEX = re.compile(
    r"(?:https?:\/\/)?(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}(?:\/[^\s]*)?",
    re.IGNORECASE
)

GITHUB_REPO_REGEX = re.compile(
    r"https?:\/\/(?:www\.)?github\.com\/([a-zA-Z0-9_-]+)\/([a-zA-Z0-9._-]+)",
    re.IGNORECASE
)

YOUTUBE_REGEX = re.compile(
    r"(?:https?:\/\/)?(?:www\.)?(?:youtube\.com\/(?:watch\?v=|shorts\/)|youtu\.be\/)([a-zA-Z0-9_-]{11})",
    re.IGNORECASE
)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"

def extract_first_url(text: str) -> Optional[str]:
    if not text:
        return None
    match = URL_REGEX.search(text)
    if match:
        url = match.group(0)
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url
        return url
    return None

async def extract_youtube_info(video_id: str, original_url: str) -> Dict:
    """Извлекает метаданные и субтитры YouTube видео"""
    info = {
        "type": "youtube_video",
        "title": "YouTube Видео",
        "url": original_url,
        "author": "",
        "raw_text": ""
    }
    
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
            resp = await client.get(oembed_url)
            if resp.status_code == 200:
                data = resp.json()
                info["title"] = data.get("title", info["title"])
                info["author"] = data.get("author_name", "")
    except Exception:
        pass

    transcript_text = ""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['ru', 'en'])
        pieces = [t['text'] for t in transcript_list[:150]]
        transcript_text = " ".join(pieces)[:3000]
    except Exception:
        pass

    info["raw_text"] = (
        f"YouTube Видео: {info['title']}\n"
        f"Автор/Канал: {info['author'] or 'Не указан'}\n"
        f"Ссылка: https://youtu.be/{video_id}\n\n"
        f"Транскрипт/Речь из видео:\n{transcript_text or 'Субтитры недоступны, анализ по метаданным'}"
    )
    return info

async def extract_github_repo_info(owner: str, repo: str) -> Dict:
    """Извлекает полную информацию о репозитории: звёзды, стек, лицензию и активность"""
    repo = repo[:-4] if repo.endswith(".git") else repo
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github.v3+json"}
    info = {
        "type": "github_repo",
        "title": f"{owner}/{repo}",
        "url": f"https://github.com/{owner}/{repo}",
        "description": "",
        "stars": 0,
        "language": "",
        "license": "Не указана",
        "last_push": "",
        "open_issues": 0,
        "readme_snippet": "",
        "raw_text": ""
    }
    
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        try:
            api_resp = await client.get(f"https://api.github.com/repos/{owner}/{repo}", headers=headers)
            if api_resp.status_code == 200:
                data = api_resp.json()
                info["description"] = data.get("description", "") or ""
                info["stars"] = data.get("stargazers_count", 0)
                info["language"] = data.get("language", "") or ""
                info["open_issues"] = data.get("open_issues_count", 0)
                info["last_push"] = (data.get("pushed_at") or "")[:10]
                
                lic = data.get("license")
                if lic and lic.get("spdx_id"):
                    info["license"] = lic.get("spdx_id")
                    
                topics = ", ".join(data.get("topics", []))
                if topics:
                    info["description"] += f" (Теги: {topics})"
        except Exception:
            pass

        readme_urls = [
            f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/README.md",
            f"https://raw.githubusercontent.com/{owner}/{repo}/main/README.md",
            f"https://raw.githubusercontent.com/{owner}/{repo}/master/README.md",
        ]
        for r_url in readme_urls:
            try:
                r_resp = await client.get(r_url, headers={"User-Agent": USER_AGENT})
                if r_resp.status_code == 200 and len(r_resp.text.strip()) > 50:
                    info["readme_snippet"] = r_resp.text[:3500]
                    break
            except Exception:
                continue

    summary_text = (
        f"GitHub Репозиторий: {info['title']}\n"
        f"Основной стек: {info['language'] or 'Не указан'} | Звёзд: {info['stars']}\n"
        f"Лицензия: {info['license']} | Последнее обновление: {info['last_push']}\n"
        f"Описание: {info['description']}\n\n"
        f"README документация (фрагмент):\n{info['readme_snippet']}"
    )
    info["raw_text"] = summary_text.strip()
    return info

async def fetch_web_page_content(url: str) -> Dict:
    """Парсит страницу: GitHub, YouTube или обычную статью в интернете"""
    yt_match = YOUTUBE_REGEX.search(url)
    if yt_match:
        video_id = yt_match.group(1)
        return await extract_youtube_info(video_id, url)

    gh_match = GITHUB_REPO_REGEX.search(url)
    if gh_match:
        owner, repo = gh_match.group(1), gh_match.group(2)
        return await extract_github_repo_info(owner, repo)

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    
    result = {
        "type": "webpage",
        "url": url,
        "title": "",
        "description": "",
        "raw_text": ""
    }

    try:
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True, verify=False) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                result["raw_text"] = f"Страница вернула статус {resp.status_code}"
                return result

            soup = BeautifulSoup(resp.text, "html.parser")

            title_tag = soup.find("title")
            if title_tag and title_tag.string:
                result["title"] = title_tag.string.strip()

            meta_desc = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
            if meta_desc and meta_desc.get("content"):
                result["description"] = meta_desc["content"].strip()

            for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "svg", "form"]):
                tag.decompose()

            paragraphs = []
            for el in soup.find_all(["h1", "h2", "h3", "p", "li"]):
                txt = el.get_text(separator=" ", strip=True)
                if len(txt) > 25:
                    paragraphs.append(txt)

            clean_text = "\n".join(paragraphs)[:3500]
            result["raw_text"] = (
                f"Заголовок: {result['title']}\n"
                f"Описание: {result['description']}\n"
                f"Текст:\n{clean_text}"
            ).strip()
            
    except Exception as e:
        result["raw_text"] = f"Ошибка загрузки ресурса {url}: {str(e)}"

    return result
