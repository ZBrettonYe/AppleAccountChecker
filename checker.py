import json
import asyncio
from playwright.async_api import async_playwright
from fake_useragent import UserAgent
import traceback


async def find_app(page):
    """边滚动边查找 app"""
    try:
        no_new_content_count = 0
        target_info = None

        while no_new_content_count < 3:
            try:
                items = await page.query_selector_all('.purchase:has([aria-label="Shadowrocket"])')

                for item in items:
                    try:
                        order_id_element = await item.query_selector(".purchase-header .second-element")
                        publisher_element = await item.query_selector(".pli-publisher")
                        price_element = await item.query_selector(".pli-price")

                        if order_id_element and publisher_element and price_element:
                            target_info = {
                                "order_id": (await order_id_element.text_content()).strip(),
                                "publisher": (await publisher_element.text_content()).strip(),
                                "price": (await price_element.text_content()).strip()
                            }
                            return target_info
                    except Exception:
                        continue

                current_height = await page.evaluate('document.body.scrollHeight')
                await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                try:
                    await page.wait_for_selector('.purchases > .loading-indicator', state='hidden')
                except Exception:
                    pass
                new_height = await page.evaluate('document.body.scrollHeight')

                if new_height == current_height:
                    no_new_content_count += 1
                else:
                    no_new_content_count = 0

            except Exception:
                no_new_content_count += 1

        return None
    except Exception as e:
        print(f"查找app时发生错误: {str(e)}")
        return None


async def login_logic(frame_locator, id, password):
    try:
        user_input = frame_locator.locator('#account_name_text_field')
        await user_input.fill(id)
        await frame_locator.locator('button#sign-in').click()

        try:
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

            await password_field.fill(password)
            await frame_locator.locator('button#sign-in').click()

            return True

        except asyncio.TimeoutError:
            return False

    except Exception as e:
        print(f"登录过程中发生错误: {e}")
    return False


async def check_verification_status(page, frame_locator):
    try:
        checks = [
            {'selector': '#errMsg', 'status': 'error_login'},
            {'selector': 'iframe#repairFrame', 'status': 'repair_iframe'},
            {'selector': 'div.verify-phone', 'status': 'phone_verification'},
            {'selector': 'div.verify-device', 'status': 'device_verification'},
            {'selector': 'div#acc-locked', 'status': 'account_locked'},
            {'selector': '.app', 'status': 'purchase_page', 'page': True},
        ]

        async def check_element(check):
            try:
                locator = (page if check.get('page')
                           else frame_locator).locator(check['selector'])
                await locator.wait_for()
                return check['status']
            except Exception:
                return None

        for future in asyncio.as_completed([check_element(check) for check in checks]):
            result = await future
            if result:
                return result

    except Exception as e:
        print(f"验证状态检查时发生错误: {str(e)}")
    return None


async def login(page, id, password):
    try:
        locator = page.locator('iframe#aid-auth-widget-iFrame')
        await locator.wait_for()

        frame_locator = locator.content_frame
        if await login_logic(frame_locator, id, password):
            verification_status = await check_verification_status(page, frame_locator)
            if verification_status == "purchase_page":
                return True
            elif verification_status == "repair_iframe":
                cancel_btn = frame_locator.frame_locator(
                    'iframe#repairFrame').locator('button.nav-cancel')
                await cancel_btn.click()
                await cancel_btn.click()
                return True
            elif verification_status == "error_login":
                error_text = await frame_locator.locator('#errMsg').inner_text()
                return f"错误提示: {error_text}"
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


async def process_account(playwright, account):
    browser = None
    try:
        browser = await playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ]
        )
        # 优化上下文配置
        context = await browser.new_context(
            bypass_csp=True,
            user_agent=UserAgent().random,
        )
        # 启用请求拦截，减少不必要的资源加载
        await context.route(
            "**/*",
            lambda route: route.abort() if route.request.resource_type in [
                "image", "media", "font"] else route.continue_()
        )

        page = await context.new_page()
        await page.goto("https://reportaproblem.apple.com/")

        login_result = await login(page, account['id'], account['password'])
        if login_result != True:
            account['check'] = f"❗登录失败: {login_result}"
            return account

        print(f"账号 {account['id']} 登录成功，开始检索软件...")
        try:
            task_purchase = asyncio.create_task(
                page.locator(".purchases").wait_for(state='visible', timeout=30000))
            task_error = asyncio.create_task(
                page.locator(".error-content").wait_for(state='visible', timeout=30000))

            done, pending = await asyncio.wait([task_purchase, task_error], return_when=asyncio.FIRST_COMPLETED)
            [task.cancel() for task in pending]

            if task_error in done:
                account['check'] = f"❗登录失败: {await page.locator(".error-content").inner_text()}"
                return account

            await page.wait_for_selector(".purchase.loaded")
            target_info = await find_app(page)

            if target_info:
                account['check'] = "✔️找到目标软件"
                account['details'] = target_info
            else:
                account['check'] = "❌未找到目标软件"
        except Exception as e:
            account['check'] = f"检索软件时发生错误: {str(e)}"

    except Exception as e:
        account['check'] = f"处理账号时发生错误: {str(e)}"
        print(f"账号 {account['id']} 处理时发生错误: {str(e)}")
        traceback.print_exc()

    finally:
        if browser:
            try:
                await browser.close()
            except Exception:
                pass

    return account


async def main():
    # Todo 添加代理，提高可并发数
    try:
        semaphore = asyncio.Semaphore(1)

        async def process_with_semaphore(playwright, account):
            async with semaphore:
                return await process_account(playwright, account)

        with open('accounts.json', 'r', encoding='utf-8') as f:
            accounts = json.load(f)

        async with async_playwright() as playwright:
            tasks = [process_with_semaphore(
                playwright, account) for account in accounts]
            updated_accounts = []

            # 使用 as_completed 来处理任务完成的结果
            for future in asyncio.as_completed(tasks):
                result = await future
                updated_accounts.append(result)
                print(f"完成账号检查: {result['id']}")

            # 按原始顺序排序结果
            sorted_accounts = sorted(updated_accounts,
                                     key=lambda x: accounts.index(next(a for a in accounts if a['id'] == x['id'])))

            with open('accounts_checked.json', 'w', encoding='utf-8') as f:
                json.dump(sorted_accounts, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"主程序发生错误: {str(e)}")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
