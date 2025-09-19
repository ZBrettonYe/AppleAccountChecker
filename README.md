# AppleAccountChecker
基于 Playwright 框架的python脚本, 用于批量查找Apple Account中是否有目标软件

## 使用步骤
1. 克隆项目
```bash
git clone https://github.com/ZBrettonYe/AppleAccountChecker.git
cd AppleAccountChecker
```

2. 安装依赖
```bash
pip install -r requirements.txt
````

3. 安装Playwright 并下载浏览器
```bash
playwright install
```

4. 运行程序
```bash
python checker.py
```

5. 参数
```json
config.json

{
  "SEARCH_APP_ID": "932747118", // apple 应用唯一id，参考https://apps.apple.com/us/app/shadowrocket/id932747118 中 id后的部分；
  "MAX_CONCURRENT": 1, // 并行检测数，需要配合 proxy list 进行使用；
  "PROXY_LIST": [], // 代理
  "HEADLESS": true, // 无窗口运行；
  "MIN_DELAY": 5,
  "MAX_DELAY": 10,
  "INPUT_FILE": "accounts.json",
  "OUTPUT_FILE": "accounts_checked.json"
}
```
6. 

## 使用指南
### 输入
需要在程序同一目录下存在 `accounts.json`, 该文件内容接口如下
```json
[
    {
        "id": "account1",
        "password": "passwordForAccount1",
        "search_app": "932747118" // 程序也可以全局设置默认软件，SEARCH_APP_ID
    },
	{
        "id": "account2",
        "password": "passwordForAccount2"
    },
]
```

### 输出
程序会在同一目录下生成 `accounts_checked.json`
