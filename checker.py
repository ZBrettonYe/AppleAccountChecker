import json
import asyncio
from playwright.async_api import async_playwright
from fake_useragent import UserAgent
import time
import random
from typing import Dict, Optional, List
import os

# ==================== 配置区域 ====================

# 搜索配置
SEARCH_APP_ID = "932747118"  # 要搜索的App名称，可修改

# 代理配置
MAX_CONCURRENT = 1  # 并发数
PROXY_LIST = [
    # HTTP代理示例
    # {"server": "http://127.0.0.1:7890"},
    # {"server": "http://proxy1.com:8080", "username": "user", "password": "pass"},
    # SOCKS5代理示例
    # {"server": "socks5://127.0.0.1:1080"},
    # {"server": "socks5://proxy2.com:1080", "username": "user", "password": "pass"},
]

# 文件配置
INPUT_FILE = "accounts.json"  # 输入文件
OUTPUT_FILE = "accounts_checked.json"  # 输出文件
TEMP_OUTPUT_FILE = "accounts_checked_temp.json"  # 临时文件
CONFIG_FILE = "config.json"  # 配置文件（可选）

# 浏览器配置
HEADLESS = True  # 是否无头模式

# 延迟配置
MIN_DELAY = 5  # 最小延迟（秒）
MAX_DELAY = 10  # 最大延迟（秒）

# ==================== 配置管理 ====================


def load_config():
    """从配置文件加载配置"""
    global SEARCH_APP_ID, MAX_CONCURRENT, PROXY_LIST, HEADLESS, MIN_DELAY, MAX_DELAY, INPUT_FILE, OUTPUT_FILE

    if not os.path.exists(CONFIG_FILE):
        return

    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config_data = json.load(f)

            SEARCH_APP_ID = config_data.get("SEARCH_APP_ID", SEARCH_APP_ID)
            MAX_CONCURRENT = config_data.get("MAX_CONCURRENT", MAX_CONCURRENT)
            PROXY_LIST = config_data.get("PROXY_LIST", PROXY_LIST)
            HEADLESS = config_data.get("HEADLESS", HEADLESS)
            MIN_DELAY = config_data.get("MIN_DELAY", MIN_DELAY)
            MAX_DELAY = config_data.get("MAX_DELAY", MAX_DELAY)
            INPUT_FILE = config_data.get("INPUT_FILE", INPUT_FILE)
            OUTPUT_FILE = config_data.get("OUTPUT_FILE", OUTPUT_FILE)

            print(f"✅ 已从 {CONFIG_FILE} 加载配置")
    except Exception as e:
        print(f"⚠️ 加载配置文件失败: {e}")


def save_config_template():
    """保存配置模板"""
    template = {
        "SEARCH_APP_ID": SEARCH_APP_ID,
        "MAX_CONCURRENT": MAX_CONCURRENT,
        "PROXY_LIST": PROXY_LIST,
        "HEADLESS": HEADLESS,
        "MIN_DELAY": MIN_DELAY,
        "MAX_DELAY": MAX_DELAY,
        "INPUT_FILE": INPUT_FILE,
        "OUTPUT_FILE": OUTPUT_FILE
    }

    template_file = "config_template.json"
    with open(template_file, 'w', encoding='utf-8') as f:
        json.dump(template, f, ensure_ascii=False, indent=2)
    print(f"📋 配置模板已保存到 {template_file}")

# ==================== 结果管理 ====================


# 全局结果存储
results = {}
results_lock = asyncio.Lock()


async def load_existing_results():
    """加载已存在的结果"""
    global results

    # 优先加载临时文件
    for file in [TEMP_OUTPUT_FILE, OUTPUT_FILE]:
        if not os.path.exists(file):
            continue

        try:
            with open(file, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
                if isinstance(existing_data, list):
                    results = {
                        item['id']: item for item in existing_data if 'id' in item}
                print(f"📂 已加载 {len(results)} 个已处理结果从 {file}")
                break
        except Exception as e:
            print(f"⚠️ 加载现有结果失败: {e}")


async def save_result(account: Dict):
    """保存单个结果并立即写入文件"""
    global results

    async with results_lock:
        # 更新结果
        results[account['id']] = account

        # 立即写入临时文件
        try:
            with open(TEMP_OUTPUT_FILE, 'w', encoding='utf-8') as f:
                json.dump(list(results.values()), f,
                          ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ 保存临时结果失败: {e}")


def get_processed_ids() -> set:
    """获取已处理的账号ID集合"""
    return set(results.keys())


def finalize_results(original_order: List[Dict]) -> List[Dict]:
    """最终保存，按原始顺序排序"""
    try:
        # 按原始顺序排序
        sorted_results = []
        for original_account in original_order:
            account_id = original_account['id']
            if account_id in results:
                sorted_results.append(results[account_id])
            else:
                # 如果某个账号未处理，保留原始信息并标记
                unprocessed = original_account.copy()
                unprocessed['check'] = "⭐未处理"
                sorted_results.append(unprocessed)

        # 保存最终文件
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(sorted_results, f, ensure_ascii=False, indent=2)

        # 删除临时文件
        if os.path.exists(TEMP_OUTPUT_FILE):
            os.remove(TEMP_OUTPUT_FILE)

        return sorted_results

    except Exception as e:
        print(f"⚠️ 最终保存失败: {e}")
        return list(results.values())

# ==================== 代理管理 ====================


proxy_index = 0
proxy_lock = asyncio.Lock()


async def get_proxy() -> Optional[Dict]:
    """轮询获取代理"""
    global proxy_index

    if not PROXY_LIST:
        return None

    async with proxy_lock:
        proxy = PROXY_LIST[proxy_index]
        proxy_index = (proxy_index + 1) % len(PROXY_LIST)
        return proxy

# ==================== 核心功能函数 ====================


async def setup_api_listeners(page):
    """设置API监听器，返回登录完成事件"""
    login_data = {}
    login_complete_event = asyncio.Event()

    def handle_login_request(request):
        if "/api/login" in request.url and request.method == "GET":
            login_data['x_apple_rap2_api'] = request.headers.get(
                "x-apple-rap2-api")

    def handle_login_response(response):
        if "/api/login" in response.url and response.status == 200:
            login_data['response'] = response
            login_complete_event.set()  # 设置事件完成

    # 设置监听器
    page.on("request", handle_login_request)
    page.on("response", handle_login_response)

    return login_complete_event, login_data


async def find_app(page, app_id: str, login_data: dict):
    """
    使用已监听到的登录数据查找App
    """
    try:
        # 等待登录响应
        if 'response' not in login_data:
            print("❌ 未监听到登录响应")
            return None

        login_json = await login_data['response'].json()
        token = login_json.get("token")
        dsid = login_json.get("dsid")
        x_apple_rap2_api = login_data.get('x_apple_rap2_api')

        if not all([token, dsid, x_apple_rap2_api]):
            print("❌ 登录数据不完整")
            return None

        # 在浏览器里发起 /api/purchase/search 请求
        purchases = await page.evaluate(f"""
async (app_id) => {{
  const resp = await fetch("/api/purchase/search", {{
    method: "POST",
    headers: {{
      "Content-Type": "application/json",
      "X-Apple-Rap2-Api": "{x_apple_rap2_api}",
      "X-Apple-Xsrf-Token": "{token}"
    }},
    credentials: "include",
    body: JSON.stringify({{ adamIds: [app_id], dsid: "{dsid}" }})
  }});
    
    if (!resp.ok) {{
        const text = await resp.text();
        return {{ error: 'API fetch failed', status: resp.status, text: text }};
    }}

    const data = await resp.json();
    const purchases = data.purchases || [];
    return purchases.flatMap(p => (p.plis || []).map(pli => {{
        const c = pli.localizedContent || {{}};
        return {{
            app_name: c.nameForDisplay,
            publisher: c.detailForDisplay,
            price: pli.amountPaid
        }};
    }}));
}}
""", app_id)

        # 检查是否返回了错误信息
        if isinstance(purchases, dict) and 'error' in purchases:
            print(f"❌ find_app API 请求失败: {purchases['error']}")
            print(f"状态码: {purchases['status']}")
            print(f"响应内容 (前500字符): {purchases['text'][:500]}")
            return None

        if purchases and len(purchases) > 0:
            return purchases
        return None

    except Exception as e:
        print(f"❌ find_app 出错: {e}")
        return None


async def login_logic(frame_locator, id: str, password: str) -> bool:
    """执行登录逻辑"""
    try:
        # 输入用户名
        await frame_locator.locator('#account_name_text_field').fill(id)
        await frame_locator.locator('button#sign-in').click()

        continue_button = frame_locator.locator('button#continue-password')
        password_field = frame_locator.locator(
            'input#password_text_field:not([tabindex="-1"])')

        task_continue = asyncio.create_task(
            continue_button.wait_for(state='visible'))
        task_password = asyncio.create_task(
            password_field.wait_for(state='visible'))
        done, pending = await asyncio.wait([task_continue, task_password], return_when=asyncio.FIRST_COMPLETED)
        [task.cancel() for task in pending]

        if task_continue in done:
            await continue_button.click()
            await password_field.wait_for(state='visible')

        # 输入密码并登录
        await password_field.fill(password)
        await frame_locator.locator('button#sign-in').click()
        return True
    except Exception as e:
        print(f"登录过程中发生错误: {e}")
    return False


async def check_verification_status(page, frame_locator):
    """检查验证状态"""
    checks = [
        {'selector': '.idms-error', 'status': 'error_login'},
        {'selector': '#errMsg', 'status': 'error_login'},
        {'selector': 'iframe#repairFrame', 'status': 'repair_iframe'},
        {'selector': 'div.verify-phone', 'status': 'phone_verification'},
        {'selector': 'div.verify-device', 'status': 'device_verification'},
        {'selector': 'div#acc-locked', 'status': 'account_locked'},
        {'selector': '.app', 'status': 'purchase_page', 'page': True},
    ]

    try:
        async def check_element(check):
            try:
                locator = (page if check.get('page')
                           else frame_locator).locator(check['selector'])
                await locator.wait_for()
                return check['status']
            except:
                return None

        for future in asyncio.as_completed([check_element(check) for check in checks]):
            result = await future
            if result:
                return result
    except Exception as e:
        print(f"验证状态检查时发生错误: {str(e)}")
    return None


async def login(page, id: str, password: str, login_data: dict):
    """执行完整登录流程"""
    try:
        # 等待登录iframe
        iframe_locator = page.locator('iframe#aid-auth-widget-iFrame')
        await iframe_locator.wait_for()
        frame_locator = iframe_locator.content_frame

        # 执行登录
        if not await login_logic(frame_locator, id, password):
            return "登录失败：无法完成登录流程"

        # 检查登录结果
        verification_status = await check_verification_status(page, frame_locator)

        if verification_status == "purchase_page":
            return True

        elif verification_status == "repair_iframe":
            # 处理修复iframe
            cancel_btn = frame_locator.frame_locator(
                'iframe#repairFrame').locator('button.nav-cancel')
            await cancel_btn.click()
            await cancel_btn.click()
            return True

        elif verification_status == "error_login":
            # 获取错误信息
            error_text = ""
            for selector in ['.idms-error', '#errMsg']:
                try:
                    error_element = frame_locator.locator(selector)
                    if await error_element.count() > 0:
                        error_text = await error_element.first.inner_text()
                        break
                except:
                    continue
            return f"错误提示: {error_text if error_text else '未知错误'}"

        elif verification_status == "phone_verification":
            return "需要进行电话验证，请处理。"

        elif verification_status == "device_verification":
            return "需要进行设备验证，请处理。"

        elif verification_status == "account_locked":
            return "账号被锁定，请处理。"

        else:
            return "啥也没命中"

    except Exception as e:
        return f"登录出错：{e}"


async def process_account(playwright, account: Dict, app_id: str = None) -> Dict:
    """处理单个账号"""
    browser = None
    start_time = time.time()
    max_retries = 2

    if app_id is None:
        app_id = account.get('search_app', SEARCH_APP_ID)

    for attempt in range(max_retries):
        try:
            # 获取代理
            proxy = await get_proxy()
            if proxy:
                print(
                    f"账号 {account['id']} 使用代理: {proxy.get('server', 'unknown')}")

            # 浏览器配置
            launch_options = {
                "headless": HEADLESS,
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-extensions",
                ]
            }

            # 如果有代理，添加代理配置
            if proxy:
                launch_options["proxy"] = proxy

            browser = await playwright.chromium.launch(**launch_options)

            context = await browser.new_context(
                bypass_csp=True,
                user_agent=UserAgent().random,
            )

            # 拦截无用资源
            await context.route(
                "**/*",
                lambda route: route.abort()
                if route.request.resource_type in ["image", "media", "font", "stylesheet"]
                else route.continue_()
            )

            page = await context.new_page()
            await page.goto("https://reportaproblem.apple.com/", wait_until="domcontentloaded")

            # 设置API监听器
            login_complete_event, login_data = await setup_api_listeners(page)

            # 登录
            login_result = await login(page, account['id'], account['password'], login_data)

            # 处理身份验证错误
            if "无法验证你的身份" in str(login_result) and attempt < max_retries - 1:
                print(f"账号 {account['id']} 遇到身份验证错误，重试中...")
                await browser.close()
                browser = None
                await asyncio.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
                continue

            if login_result != True:
                account['check'] = f"◉登录失败: {login_result}"
                break

            print(f"账号 {account['id']} 登录成功，检索 [{app_id}]...")

            # 检查是否获取到了登录数据，等待登录完成或错误页面
            try:
                # 等待错误页面或登录API完成
                error_task = asyncio.create_task(
                    page.locator(".error-content").wait_for(state='visible')
                )
                login_task = asyncio.create_task(login_complete_event.wait())

                done, pending = await asyncio.wait(
                    [error_task, login_task],
                    return_when=asyncio.FIRST_COMPLETED
                )

                # 取消未完成的任务
                for task in pending:
                    task.cancel()

                # 检查是否出现错误页面
                if error_task in done:
                    error_text = await page.locator('.error-content').inner_text()
                    account['check'] = f"◉登录失败: {error_text}"
                    break

                # 登录成功，查找App
                if login_task in done:
                    target_info = await find_app(page, app_id, login_data)
                    if target_info:
                        account['check'] = f"✔️ 找到目标软件 [{app_id}]"
                        account['details'] = target_info
                    else:
                        account['check'] = f"❌未找到软件 [{app_id}]"
                    break

            except Exception as e:
                account['check'] = f"检索软件时发生错误: {str(e)}"
                if attempt < max_retries - 1:
                    print(f"账号 {account['id']} 处理失败，重试中...")
                    await browser.close()
                    browser = None
                    await asyncio.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
                    continue

        except Exception as e:
            if attempt < max_retries - 1:
                print(f"账号 {account['id']} 处理失败，重试中...")
                await asyncio.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
                continue
            account['check'] = f"处理失败: {str(e)}"

        finally:
            if browser:
                try:
                    await browser.close()
                except:
                    pass

    # 记录处理信息
    account['process_time'] = f"{time.time() - start_time:.2f}秒"
    account['timestamp'] = time.strftime("%Y-%m-%d %H:%M:%S")

    # 保存结果
    await save_result(account)

    return account


async def main():
    """主函数"""
    try:
        # 加载配置
        load_config()

        # 生成配置模板
        if not os.path.exists(CONFIG_FILE):
            save_config_template()
            print(f"💡 提示：可以编辑 config_template.json 并重命名为 {CONFIG_FILE}")

        # 根据PROXY_LIST自动判断并发数
        global MAX_CONCURRENT
        if PROXY_LIST and MAX_CONCURRENT == 1:
            MAX_CONCURRENT = min(3, len(PROXY_LIST))  # 最多3个并发

        # 初始化结果管理
        await load_existing_results()

        # 读取账号
        with open(INPUT_FILE, 'r', encoding='utf-8') as f:
            accounts = json.load(f)

        # 过滤已处理账号
        processed_ids = get_processed_ids()
        accounts_to_process = []

        for account in accounts:
            # 检查账号是否有自定义的搜索App（支持在accounts.json中为每个账号单独配置）
            if 'search_app' not in account:
                account['search_app'] = SEARCH_APP_ID

            if account['id'] not in processed_ids:
                accounts_to_process.append(account)
            else:
                print(f"⭐ 跳过已处理: {account['id']}")

        if not accounts_to_process:
            print("✅ 所有账号都已处理完成！")
            return

        # 显示运行信息
        print(f"\n{'='*60}")
        print(f"🚀 Apple账号检查器")
        print(f"{'='*60}")
        print(f"📋 待处理: {len(accounts_to_process)}/{len(accounts)}")
        print(f"🔍 搜索软件: {SEARCH_APP_ID}")
        print(f"🌐 模式: {'代理' if PROXY_LIST else '直连'}")
        print(f"⚡ 并发数: {MAX_CONCURRENT}")
        print(f"{'='*60}\n")

        async with async_playwright() as playwright:
            if MAX_CONCURRENT == 1:
                # 顺序处理
                for i, account in enumerate(accounts_to_process):
                    print(f"\n⏳ 处理 {i+1}/{len(accounts_to_process)}")

                    app_id = account.get('search_app', SEARCH_APP_ID)
                    result = await process_account(playwright, account, app_id)

                    print(
                        f"✅ {result['id']} - {result['check']} ({result.get('process_time', 'N/A')})")
            else:
                # 并发处理
                semaphore = asyncio.Semaphore(MAX_CONCURRENT)

                async def process_with_limit(account):
                    async with semaphore:
                        return await process_account(
                            playwright, account,
                            account.get('search_app', SEARCH_APP_ID)
                        )

                tasks = [process_with_limit(acc)
                         for acc in accounts_to_process]

                for i, future in enumerate(asyncio.as_completed(tasks), 1):
                    result = await future
                    print(
                        f"[{i}/{len(tasks)}] ✅ {result['id']} - {result['check']}")

        # 保存最终结果
        final_results = finalize_results(accounts)

        # 统计
        stats = {
            '✔️成功': sum(1 for a in final_results if '✔️' in a.get('check', '')),
            '❌未找到': sum(1 for a in final_results if '❌' in a.get('check', '')),
            '◉失败': sum(1 for a in final_results if '◉' in a.get('check', '')),
            '⭐未处理': sum(1 for a in final_results if '⭐' in a.get('check', ''))
        }

        print(f"\n{'='*60}")
        print(f"✅ 处理完成！")
        print(f"📄 结果: {OUTPUT_FILE}")
        print(f"\n📊 统计:")
        for key, value in stats.items():
            if value > 0:
                print(f"  {key}: {value}")
        print(f"{'='*60}\n")

    except FileNotFoundError as e:
        print(f"❌ 找不到文件: {INPUT_FILE}")
    except Exception as e:
        print(f"❌ 程序错误: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
