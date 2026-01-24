#!/usr/bin/env python3
from os import environ
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import Page

# Robustly match .env file
def load_environment():
    """
    .env 파일을 찾아 로드합니다.
    우선순위:
    1. src/ 상위 디렉토리 (프로젝트 루트)
    2. 현재 작업 디렉토리
    """
    # 1. Check project root (relative to this file)
    project_root = Path(__file__).resolve().parent.parent
    env_path = project_root / '.env'
    
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
        return

    # 2. Check current working directory
    cwd_env = Path.cwd() / '.env'
    if cwd_env.exists():
        load_dotenv(dotenv_path=cwd_env)
        return
        
    # 3. Last fallback: try default load_dotenv (searches up tree)
    load_dotenv()

load_environment()

USER_ID = environ.get('USER_ID')
PASSWD = environ.get('PASSWD')


def login(page: Page) -> None:
    """
    동행복권 사이트에 로그인합니다.
    
    Args:
        page: Playwright Page 객체 (호출자가 생성하여 주입)
    
    Raises:
        ValueError: USER_ID 또는 PASSWD 환경변수가 없을 경우
    """
    if not USER_ID or not PASSWD:
        raise ValueError("❌ USER_ID or PASSWD not found in environment variables.")
    
    print('Starting login process...')
    page.goto("https://www.dhlottery.co.kr/login", timeout=30000, wait_until="domcontentloaded")
    
    page.locator("#inpUserId").fill(USER_ID)
    page.locator("#inpUserPswdEncn").fill(PASSWD)
    page.click("#btnLogin")
    
    # Wait for login to complete
    page.wait_for_load_state("networkidle")
    print('✅ Logged in successfully')
