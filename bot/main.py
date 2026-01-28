"""
Telegram Bot 主流程

实现最小命令集：/nav /buy_sim /settle /alert_add /alert_list
"""

import os
from datetime import date, datetime
from typing import Optional

import asyncpg
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from adapters import EastMoneyAdapter
from core.alerts import AlertEngine, AlertRuleParams, AlertRuleType
from core.events import TradeService, TradeType
from core.types import DataWithSource, DataSource, NAV, QualityFlag


class TradingBot:
    """基金交易系统 Bot"""

    def __init__(self):
        self.db_pool: Optional[asyncpg.Pool] = None
        self.adapter = EastMoneyAdapter()
        self.trade_svc: Optional[TradeService] = None
        self.alert_engine: Optional[AlertEngine] = None

    async def init_db(self):
        """初始化数据库连接"""
        db_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost/trading_plus")
        self.db_pool = await asyncpg.create_pool(db_url, min_size=2, max_size=10)

        self.trade_svc = TradeService(self.db_pool)
        self.alert_engine = AlertEngine(self.db_pool)

    async def close(self):
        """关闭连接"""
        if self.db_pool:
            await self.db_pool.close()
        await self.adapter.close()

    # ========================================================================
    # 命令处理
    # ========================================================================

    async def cmd_nav(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /nav <code> [n]

        查询基金净值。返回最近 n 天净值数据（默认 7 天）。
        """
        if not update.message or not context.args:
            await update.message.reply_text("用法: /nav <基金代码> [天数]")
            return

        fund_code = context.args[0]
        days = int(context.args[1]) if len(context.args) > 1 else 7

        try:
            # 获取净值序列
            end_date = date.today()
            start_date = end_date - datetime.timedelta(days=days * 2)  # 多取一些以防节假日

            result = await self.adapter.fetch_nav_series(fund_code, start_date.isoformat(), end_date.isoformat())

            # 格式化输出
            navs = result.data[-days:]  # 取最后 n 天
            lines = [
                f"📊 *{fund_code} 净值走势*",
                f"数据源: {result.data_source.value}",
                f"更新时间: {result.last_updated_at.strftime('%Y-%m-%d %H:%M:%S')}",
                "",
            ]

            for nav in navs:
                status_emoji = "✅" if QualityFlag.OK in result.quality_flags else "⚠️"
                daily_change = f" ({nav['daily_pct']:+.2f}%)" if nav.get("daily_pct") else ""
                lines.append(f"{status_emoji} `{nav['nav_date']}`: {nav['nav']:.4f}{daily_change}")

            lines.append("\n⚠️ 本系统为模拟交易，非投资建议")

            await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

        except Exception as e:
            await update.message.reply_text(f"❌ 查询失败: {e}")

    async def cmd_buy_sim(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /buy_sim <code> <amount>

        模拟买入。创建买入交易事件。
        """
        if not update.message or not context.args or len(context.args) < 2:
            await update.message.reply_text("用法: /buy_sim <基金代码> <金额>")
            return

        fund_code = context.args[0]
        try:
            amount = float(context.args[1])
        except ValueError:
            await update.message.reply_text("❌ 金额必须是数字")
            return

        user_id = update.effective_user.id

        try:
            # 获取当前净值
            result = await self.adapter.fetch_nav(fund_code)
            nav_data = result.data
            nav_price = nav_data["nav"]

            # 创建交易
            trade = await self.trade_svc.create_trade(  # type: ignore[union-attr]
                user_id=user_id,
                fund_code=fund_code,
                trade_type=TradeType.BUY,
                amount=amount,
                shares=None,
                nav_price=nav_price,
                trade_date=date.today(),
                client_msg_id=str(update.message.message_id),
            )

            shares = amount / nav_price

            await update.message.reply_text(
                f"✅ 模拟买入成功\n"
                f"基金: {fund_code}\n"
                f"金额: ¥{amount:.2f}\n"
                f"净值: {nav_price:.4f}\n"
                f"份额: {shares:.2f}\n"
                f"交易ID: `{trade.trade_id}`\n\n"
                f"⚠️ 模拟交易，T+1 结算",
                parse_mode="Markdown",
            )

        except Exception as e:
            await update.message.reply_text(f"❌ 买入失败: {e}")

    async def cmd_settle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /settle [trade_id]

        手动触发结算（默认结算所有待结算交易）。
        """
        if not update.message:
            return

        user_id = update.effective_user.id

        try:
            if context.args:
                # 结算指定交易
                trade_id = context.args[0]
                # 这里需要实现 UUID 解析和单独结算
                await update.message.reply_text("⚠️ 指定交易结算功能开发中")
            else:
                # 结算所有待结算交易
                rows = await self.db_pool.fetch(  # type: ignore[union-attr]
                    """
                    SELECT trade_id FROM simulation_trades
                    WHERE user_id = $1 AND trade_status = 'created'
                    ORDER BY trade_date ASC
                    """,
                    user_id,
                )

                count = 0
                for row in rows:
                    await self.trade_svc.settle_trade(row["trade_id"])  # type: ignore[union-attr]
                    count += 1

                await update.message.reply_text(f"✅ 结算完成，共 {count} 笔交易")

        except Exception as e:
            await update.message.reply_text(f"❌ 结算失败: {e}")

    async def cmd_alert_add(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /alert_add <code> <type> <threshold>

        添加预警规则。
        类型: threshold(阈值), drawdown(回撤), volatility(波动)
        示例: /alert_add 000001 threshold 1.5
        """
        if not update.message or not context.args or len(context.args) < 3:
            await update.message.reply_text(
                "用法: /alert_add <基金代码> <类型> <阈值>\n"
                "类型: threshold(阈值), drawdown(回撤%), volatility(波动%)"
            )
            return

        fund_code = context.args[0]
        rule_type_str = context.args[1].lower()
        threshold = float(context.args[2])

        user_id = update.effective_user.id

        try:
            # 映射规则类型
            type_map = {
                "threshold": AlertRuleType.THRESHOLD,
                "drawdown": AlertRuleType.DRAWDOWN,
                "volatility": AlertRuleType.VOLATILITY,
            }

            if rule_type_str not in type_map:
                await update.message.reply_text("❌ 不支持的规则类型")
                return

            rule_type = type_map[rule_type_str]

            # 构建参数
            if rule_type == AlertRuleType.THRESHOLD:
                params = AlertRuleParams(threshold_value=threshold)
            else:
                params = AlertRuleParams(threshold_pct=threshold)

            # 创建规则
            rule = await self.alert_engine.create_rule(  # type: ignore[union-attr]
                user_id=user_id,
                fund_code=fund_code,
                rule_type=rule_type,
                params=params,
            )

            await update.message.reply_text(
                f"✅ 预警规则已创建\n"
                f"基金: {fund_code}\n"
                f"类型: {rule_type_str}\n"
                f"阈值: {threshold}\n"
                f"规则ID: `{rule.rule_id}`",
                parse_mode="Markdown",
            )

        except Exception as e:
            await update.message.reply_text(f"❌ 创建规则失败: {e}")

    async def cmd_alert_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /alert_list

        列出所有预警规则。
        """
        if not update.message:
            return

        user_id = update.effective_user.id

        try:
            rules = await self.alert_engine.list_rules(user_id)  # type: ignore[union-attr]

            if not rules:
                await update.message.reply_text("📋 暂无预警规则")
                return

            lines = ["📋 *我的预警规则*\n"]
            for rule in rules:
                status = "🔔" if rule.enabled else "🔕"
                fund = rule.fund_code or "全部"
                lines.append(
                    f"{status} `{fund}` {rule.rule_type.value} "
                    f"(ID: `{rule.rule_id}`)"
                )

            await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

        except Exception as e:
            await update.message.reply_text(f"❌ 查询失败: {e}")

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """欢迎消息"""
        if not update.message:
            return

        help_text = """
🤖 *基金交易模拟系统*

可用命令:
• /nav <代码> [天数] - 查询净值走势
• /buy_sim <代码> <金额> - 模拟买入
• /settle [交易ID] - 结算交易
• /alert_add <代码> <类型> <阈值> - 添加预警
• /alert_list - 列出预警规则

⚠️ 本系统为模拟交易，非投资建议
        """
        await update.message.reply_text(help_text, parse_mode="Markdown")

    # ========================================================================
    # 主入口
    # ========================================================================

    def run(self):
        """运行 Bot"""
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN 环境变量未设置")

        app = Application.builder().token(token).build()

        # 注册命令处理器
        app.add_handler(CommandHandler("start", self.cmd_start))
        app.add_handler(CommandHandler("nav", self.cmd_nav))
        app.add_handler(CommandHandler("buy_sim", self.cmd_buy_sim))
        app.add_handler(CommandHandler("settle", self.cmd_settle))
        app.add_handler(CommandHandler("alert_add", self.cmd_alert_add))
        app.add_handler(CommandHandler("alert_list", self.cmd_alert_list))

        # 启动前初始化
        async def post_init(app: Application) -> None:  # type: ignore[no-untyped-def]
            await self.init_db()

        app.post_init = post_init

        # 运行
        print("Bot 启动中...")
        app.run_polling(allowed_updates=["message"])


def main():
    """主入口"""
    bot = TradingBot()
    try:
        bot.run()
    finally:
        import asyncio
        asyncio.run(bot.close())


if __name__ == "__main__":
    main()
