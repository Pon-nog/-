"""品赞代理签到【独立单文件版】，适配GitHub Actions + WxPusher推送
原参考：only_for_happly 品赞逻辑，账号#密码登录后领取IP，支持多账号。
环境变量说明（在Github Secrets配置）：
PINZAN_ACCOUNTS  多账号格式：账号1#密码1|账号2#密码2
WXPUSHER_TOKEN   WxPusher的APP_TOKEN，AT_开头
WXPUSHER_TOPIC   WxPusher主题ID(数字)，也可以填uid
"""
from __future__ import annotations
import asyncio
import base64
import logging
import random
import requests
import os

# 配置日志
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

PINZAN_LOGIN_URL = "https://service.ipzan.com/users-login"
PINZAN_RECEIVE_URL = "https://service.ipzan.com/home/userWallet-receive"
FIXED_KEY = "QWERIPZAN1290QWER"


def _encrypt_account(account: str, password: str) -> str:
    plain = f"{account}{FIXED_KEY}{password}"
    encoded = base64.b64encode(plain.encode("utf-8")).decode("utf-8")
    random_hex = "".join(hex(int(random.random() * 10**16))[2:] for _ in range(80)).ljust(
        400, "0"
    )[:400]
    parts = [
        random_hex[:100],
        encoded[:8],
        random_hex[100:200],
        encoded[8:20],
        random_hex[200:300],
        encoded[20:],
        random_hex[300:400],
    ]
    return "".join(parts)


def _run_pinzan_sync(account: str, password: str) -> tuple[bool, str]:
    try:
        session = requests.Session()
        session.headers.update(
            {
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json;charset=UTF-8",
                "Origin": "https://ipzan.com",
                "Referer": "https://ipzan.com/",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            }
        )
        enc = _encrypt_account(account, password)
        r = session.post(
            PINZAN_LOGIN_URL, json={"account": enc, "source": "ipzan-home-one"}, timeout=15
        )
        r.raise_for_status()
        data = r.json()
        if data.get("code") != 0:
            return False, data.get("message", "登录失败")
        token = (data.get("data") or {}).get("token")
        if not token:
            return False, "未返回 Token"
        session.headers["Authorization"] = f"Bearer {token}"
        r2 = session.get(PINZAN_RECEIVE_URL, timeout=15)
        r2.raise_for_status()
        rec = r2.json()
        code = rec.get("code")
        msg = rec.get("message", "")
        if code == 0:
            return True, f"领取成功：{rec.get('data', '')}"
        if code == -1 and "领取过" in str(msg):
            return True, f"本周已领：{msg}"
        return False, msg or "领取失败"
    except Exception as e:
        logger.warning("品赞签到：请求失败 %s", e)
        return False, str(e)


def send_wxpusher(app_token: str, topic_id: str, content: str, summary: str = "品赞签到通知"):
    """WxPusher消息推送"""
    if not app_token:
        logger.warning("未配置WxPusher Token，跳过推送")
        return
    url = "https://wxpusher.zjiecode.com/api/send/message"
    payload = {
        "appToken": app_token,
        "topicIds": [int(topic_id)] if topic_id else [],
        "content": content,
        "summary": summary
    }
    try:
        res = requests.post(url, json=payload, timeout=15)
        logger.info(f"WxPusher推送结果: {res.json()}")
    except Exception as e:
        logger.error(f"WxPusher推送异常: {e}")


async def main():
    # 读取环境变量
    raw_accounts = os.getenv("PINZAN_ACCOUNTS", "")
    wxpusher_token = os.getenv("WXPUSHER_TOKEN", "")
    wxpusher_topic = os.getenv("WXPUSHER_TOPIC", "")

    if not raw_accounts:
        logger.error("未读取到PINZAN_ACCOUNTS环境变量！格式：账号1#密码1|账号2#密码2")
        return

    # 解析多账号
    account_list = []
    for item in raw_accounts.split("|"):
        item = item.strip()
        if "#" in item:
            acc, pwd = item.split("#", maxsplit=1)
            acc = acc.strip()
            pwd = pwd.strip()
            if acc and pwd:
                account_list.append({"account": acc, "password": pwd})

    if not account_list:
        logger.error("解析账号失败，请检查PINZAN_ACCOUNTS格式")
        return

    logger.info(f"品赞签到：开始执行（共 {len(account_list)} 个账号）")
    result_text = ""
    any_success = False

    for idx, acc_info in enumerate(account_list):
        acc = acc_info["account"]
        pwd = acc_info["password"]
        masked_acc = acc[:3] + "****" + acc[-4:] if len(acc) >=7 else "***"
        logger.info(f"===== 正在执行账号{idx+1}: {masked_acc} =====")
        try:
            ok, msg = await asyncio.to_thread(_run_pinzan_sync, acc, pwd)
        except Exception as e:
            logger.error(f"账号{idx+1}执行异常：{e}")
            ok, msg = False, str(e)

        if ok:
            any_success = True
        status_str = "✅成功" if ok else "❌失败"
        line = f"账号{masked_acc}：{status_str}\n> {msg}\n"
        result_text += line
        logger.info(line)

    # 汇总消息推送微信
    final_title = "品赞签到【全部完成】"
    final_msg = f"品赞签到任务执行完毕\n任务汇总：\n{result_text}"
    send_wxpusher(wxpusher_token, wxpusher_topic, final_msg, summary=final_title)
    logger.info("品赞签到任务全部结束")


if __name__ == "__main__":
    asyncio.run(main())
