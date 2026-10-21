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


def handle_password_notice_if_present(page: Page) -> bool:
    """
    동행복권 비밀번호 만료/변경 안내 페이지(ExpryPswdNoti 등)가 나타났을 경우
    '다음에 변경하기' 또는 '90일 후 변경' 등을 클릭하여 세션을 정상 유지합니다.
    """
    current_url = page.url
    if not ("ExpryPswdNoti" in current_url or "expry" in current_url.lower() or "pswd" in current_url.lower()):
        return False

    print("⚠️ 비밀번호 변경 안내 페이지(ExpryPswdNoti) 감지! '다음에 변경' 처리 시도...")
    page.screenshot(path="debug_password_notice.png")
    try:
        with open("debug_password_notice.html", "w", encoding="utf-8") as f:
            f.write(page.content())
        print("📄 debug_password_notice.html 저장 완료")
    except Exception:
        pass

    dismiss_selectors = [
        "text=/다음에/",
        "text=/90일/",
        "text=/나중에/",
        "text=/연장/",
        "text=/취소/",
        "button:has-text('다음에')",
        "a:has-text('다음에')",
        "button:has-text('90일')",
        "a:has-text('90일')",
        "button:has-text('나중에')",
        "a:has-text('나중에')",
        "button:has-text('취소')",
        "a:has-text('취소')",
        "button:has-text('확인')",
        "input[value*='다음']",
        "input[value*='90일']",
        "input[value*='나중']",
        "input[value*='취소']",
        "input[value*='확인']",
        "#btnNext",
        "#btnCancel",
        ".btn_common:has-text('다음')",
        "[onclick*='next']",
        "[onclick*='later']",
        "[onclick*='defer']",
        "[onclick*='postpone']",
        "[onclick*='cancel']"
    ]
    dismissed = False
    for sel in dismiss_selectors:
        try:
            btn = page.locator(sel)
            if btn.count() > 0 and btn.first.is_visible(timeout=1000):
                print(f"👉 비밀번호 변경 연기 버튼 클릭: {sel}")
                btn.first.click(timeout=3000)
                dismissed = True
                time.sleep(2)
                break
        except Exception:
            pass

    if not dismissed:
        try:
            all_buttons = page.locator("button, a.btn, a[class*='btn'], input[type='button'], a")
            for i in range(min(all_buttons.count(), 20)):
                txt = all_buttons.nth(i).inner_text(timeout=500).strip()
                if any(k in txt for k in ["다음", "90일", "나중", "취소", "연장"]):
                    print(f"👉 버튼 텍스트 매칭 클릭: '{txt}'")
                    all_buttons.nth(i).click(timeout=3000)
                    dismissed = True
                    time.sleep(2)
                    break
        except Exception as e:
            print(f"⚠️ 버튼 텍스트 탐색 중 오류: {e}")

    # 페이지 이동 확인 및 /main으로 전환
    if "ExpryPswdNoti" in page.url or "pswd" in page.url.lower():
        print("🌐 메인 페이지(/main)로 명시적 이동...")
        try:
            page.goto("https://www.dhlottery.co.kr/main", timeout=30000, wait_until="domcontentloaded")
            time.sleep(2)
        except Exception as e:
            print(f"⚠️ 메인 이동 실패: {e}")

    return True


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
            
            # Auto accept any alerts (e.g., password change notice)
            page.on("dialog", lambda dialog: dialog.accept())

            # Navigate to login page with multiple fallbacks and fast selector wait
            login_urls = [
                "https://www.dhlottery.co.kr/login",
                "https://www.dhlottery.co.kr/user.do?method=login",
                "https://dhlottery.co.kr/user.do?method=login"
            ]
            loaded = False
            for target_url in login_urls:
                try:
                    print(f"🔗 로그인 페이지 접속 시도: {target_url}")
                    page.goto(target_url, timeout=30000, wait_until="commit")
                    page.wait_for_selector("#inpUserId", state="visible", timeout=20000)
                    loaded = True
                    break
                except Exception as nav_err:
                    print(f"⚠️ {target_url} 접속 지연 ({nav_err}), 다음 주소 시도...")
                    time.sleep(2)
            
            if not loaded:
                print("⚠️ 직접 URL 접속 재시도 (domcontentloaded)...")
                page.goto("https://www.dhlottery.co.kr/login", timeout=45000, wait_until="domcontentloaded")
                page.wait_for_selector("#inpUserId", state="visible", timeout=20000)
            
            # Wait for page to settle
            time.sleep(1)
            
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
            
            # Check if password change notice (ExpryPswdNoti) appeared
            handle_password_notice_if_present(page)
            current_url = page.url
            
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
            
            # If not yet confirmed or still not on normal page, ensure we navigate to main
            if not logged_in or "ExpryPswdNoti" in page.url:
                try:
                    page.goto("https://www.dhlottery.co.kr/main", timeout=30000, wait_until="domcontentloaded")
                    time.sleep(2)
                    for indicator in login_indicators:
                        try:
                            element = page.locator(indicator)
                            if element.count() > 0:
                                logged_in = True
                                print(f"✅ 메인 페이지에서 로그인 확인됨: {indicator}")
                                break
                        except Exception:
                            pass
                except Exception as e:
                    print(f"⚠️ 메인 이동 확인 중 오류: {e}")

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
