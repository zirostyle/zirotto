#!/usr/bin/env python3
import time
from os import environ
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

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


def login(page: Page, max_retries: int = 3) -> None:
    """
    동행복권 사이트에 로그인합니다.
    
    Args:
        page: Playwright Page 객체 (호출자가 생성하여 주입)
        max_retries: 최대 재시도 횟수
    
    Raises:
        ValueError: USER_ID 또는 PASSWD 환경변수가 없을 경우
        Exception: 로그인 실패 시
    """
    if not USER_ID or not PASSWD:
        raise ValueError("❌ USER_ID or PASSWD not found in environment variables.")
    
    last_error = None
    
    for retry in range(max_retries):
        try:
            if retry > 0:
                print(f"🔄 로그인 재시도 {retry}/{max_retries-1}")
                time.sleep(5)  # Wait before retry
            
            print('Starting login process...')
            
            # Navigate to login page with longer timeout
            try:
                page.goto("https://www.dhlottery.co.kr/login", timeout=60000, wait_until="domcontentloaded")
            except PlaywrightTimeoutError:
                print("⚠️ 로그인 페이지 로드 타임아웃, 재시도 중...")
                time.sleep(3)
                page.goto("https://www.dhlottery.co.kr/login", timeout=60000, wait_until="load")
            
            # Wait for page to settle
            time.sleep(2)
            
            # Fill login form
            page.locator("#inpUserId").fill(USER_ID)
            page.locator("#inpUserPswdEncn").fill(PASSWD)
            
            # Take screenshot before login
            page.screenshot(path="debug_before_login.png")
            print("📸 로그인 전 스크린샷: debug_before_login.png")
            
            # Click login button
            page.click("#btnLogin")
            
            # Wait for navigation or error
            print("⏳ 로그인 처리 대기 중...")
            try:
                page.wait_for_load_state("networkidle", timeout=45000)
            except PlaywrightTimeoutError:
                print("⚠️ networkidle 타임아웃, 계속 진행...")
                page.wait_for_load_state("domcontentloaded", timeout=10000)
            
            # Take screenshot after login attempt
            page.screenshot(path="debug_after_login.png")
            print("📸 로그인 후 스크린샷: debug_after_login.png")
            
            # Check current URL
            current_url = page.url
            print(f"📍 로그인 후 URL: {current_url}")
            
            # Check if still on login page
            if "/login" in current_url:
                # Look for error messages
                error_selectors = [
                    ".error_msg",
                    ".alert",
                    "[class*='error']",
                    "[class*='alert']",
                    "//div[contains(@class, 'error')]",
                    "//div[contains(@class, 'alert')]",
                    "//span[contains(@class, 'error')]"
                ]
                
                error_msg = None
                for selector in error_selectors:
                    try:
                        error_el = page.locator(selector)
                        if error_el.count() > 0:
                            error_msg = error_el.first.inner_text(timeout=2000)
                            if error_msg:
                                break
                    except:
                        pass
                
                # Save HTML for debugging
                with open("debug_login_page.html", "w", encoding="utf-8") as f:
                    f.write(page.content())
                print("📄 로그인 페이지 HTML 저장: debug_login_page.html")
                
                if error_msg:
                    raise Exception(f"❌ 로그인 실패: {error_msg}")
                else:
                    raise Exception("❌ 로그인 실패: 로그인 페이지에서 벗어나지 못했습니다. 아이디/비밀번호를 확인하세요.")
            
            # Verify we're logged in by checking for user-specific elements
            print("🔍 로그인 상태 확인 중...")
            
            # Wait a bit for the page to settle
            time.sleep(2)
            
            # Check for logout button or user info (common indicators of successful login)
            logged_in = False
            login_indicators = [
                "text=/로그아웃/",
                "text=/마이페이지/",
                "[href*='logout']",
                "[href*='mypage']",
                "#gnb"
            ]
            
            for indicator in login_indicators:
                try:
                    element = page.locator(indicator)
                    if element.count() > 0:
                        logged_in = True
                        print(f"✅ 로그인 확인됨: {indicator}")
                        break
                except:
                    pass
            
            if not logged_in:
                raise Exception("❌ 로그인 검증 실패: 로그인 상태를 확인할 수 없습니다.")
            
            print('✅ Logged in successfully')
            return  # Success!
            
        except Exception as e:
            last_error = e
            print(f"❌ 로그인 시도 실패: {e}")
            if retry < max_retries - 1:
                print(f"⏳ {5} 초 후 재시도...")
                time.sleep(5)
            else:
                print("❌ 모든 로그인 시도 실패")
    
    # If we get here, all retries failed
    raise Exception(f"❌ 로그인 실패 (최대 재시도 횟수 초과): {last_error}")
