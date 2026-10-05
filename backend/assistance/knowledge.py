"""Versioned product reference shared by the handbook and grounded assistant."""

ARTICLES = [
    dict(
        id="start",
        title="Marketplace, public agents and personal instances",
        route="/",
        keywords="agent strategy marketplace overview difference агент стратег разница обзор биржа платформ",
        body="Tracy is a marketplace for AI trading agents with inspectable results. Start with the public agent marketplace, compare versioned strategies and inspect historical tests, risk and signed paper records. A public agent is the developer's identity and published strategy track record. A strategy is its versioned recipe. A personal instance is your own private executor with separate capital, limits, approvals and history. Choose Test with my limits, review the selected version, rerun tests and deploy your paper instance. Author trades are never copied. Developer studio supports evaluations, version improvements and explicit publication. Current runners execute supported deterministic templates, not arbitrary external AI models; AI capability and real exchange trading are not certified. Home is public discovery; My workspace is personal monitoring.",
        ru="Tracy — биржа AI trading agents с проверяемыми результатами. Начните с публичного каталога: сравните агентов, версии стратегий, риск, тесты и доказательства. Публичный агент — идентичность разработчика с опубликованной стратегией и историей. Стратегия — версия торгового рецепта. Личный экземпляр — отдельный исполнитель с вашими лимитами и собственной историей. Test with my limits → свои настройки → тесты → review → paper-экземпляр. Сделки автора не копируются. Developer studio нужен для тестирования, публикации и улучшения версий. Сейчас исполнение работает на поддерживаемых алгоритмических шаблонах, а не произвольных AI-моделях; это исторический paper replay, не реальные биржевые сделки.",
    ),
    dict(
        id="leaderboard",
        title="Leaderboard eligibility and comparison",
        route="/leaderboard",
        keywords="leaderboard rank compare ranking comparison рейтинг лидер сравнен сравни",
        body="The leaderboard ranks publicly listed agent strategy versions using recorded paper results. Eligibility requires a complete 96-candle replay, at least five closed trades and all recorded fills verified. Select a comparison group with matching source provider, market, interval, replay period, initial capital, fee and slippage settings. Rank by cumulative paper return descending or maximum drawdown ascending; equal values share rank. Different strategy rules and risk limits remain visible in Compare agents. Only the 100 latest updated publications are considered. Unfinished or insufficient samples stay in the marketplace without a rank. Publication is author-selected, not an independent benchmark competition. A single entry does not demonstrate superiority; historical ranks do not predict profitability.",
        ru="Leaderboard сравнивает опубликованные версии стратегий агентов. Нужны 96 обработанных свечей, минимум 5 закрытых сделок и проверка всех записанных исполнений. Выберите группу с одинаковыми источником, парой, интервалом, историческим периодом, капиталом, комиссиями и проскальзыванием. Сортировка — по доходности или минимальной просадке; равные значения имеют одинаковое место. Лимиты риска и правила могут отличаться: смотрите Compare agents. Учитываются до 100 последних обновлённых публикаций. Малая выборка остаётся в каталоге без рейтинга. Публикация добровольная; это не независимое соревнование и не прогноз прибыли.",
    ),
    dict(
        id="intent",
        title="Describe intent and fill the form",
        route="/agents/new",
        keywords="intent describe text fill capital name намер текст заполн капитал назови",
        body="State the market, strategy, capital, maximum position/trade, daily loss and approval threshold. Example: Trade SOL/USDC with momentum, capital 1000 USDC, max position 100 USDC, max trade 50 USDC, daily loss 3%, approval above 40 USDC. Only explicitly recognized values are extracted; remaining values are labeled existing settings/defaults. A dollar daily-loss request is converted to a percentage of starting capital and disclosed as an approximation: enforcement uses daily opening equity. Contradictory or unsupported requests require clarification. Review all values before testing. Editing any tested configuration invalidates its review.",
        ru="Укажите рынок, стратегию, капитал и лимиты: «SOL/USDC, тренд, капитал 1000 USDC, позиция 100 USDC, сделка 50 USDC, дневной убыток 3%, подтверждение от 40 USDC». Распознанные значения заполняют форму; остальные отмечаются как исходные настройки. Денежный дневной лимит переводится в процент начального капитала — это приближение, потому что при исполнении база расчёта — капитал на начало дня. Неясные или противоречивые требования нужно уточнить.",
    ),
    dict(
        id="guardrails",
        title="Guardrails and actual policy checks",
        route="/infrastructure",
        keywords="guardrail risk limit check safety лимит риск провер безопас",
        body="Before each paper order, Tracy checks current agent state, version, permitted market/assets, trade size, slippage, position value, available cash and inventory, loss thresholds, reservations and human approval. Onboarding scenarios call this same evaluator in an isolated test ledger. Each result exposes its input, expected decision and actual reason. Scenario portfolios are deliberate boundary test inputs, not market observations or trading results. Historical strategy backtests do not apply guardrails; paper replay does. Approval blocks execution until the owner decides; limits are rechecked. Loss thresholds block new buys; open positions can still lose value. Position/trade limits are USDC, daily loss/drawdown are percentages.",
        ru="Перед каждой paper-сделкой проверяются состояние агента, версия, разрешённый рынок, размер сделки и позиции, проскальзывание, деньги, остаток актива, потери и подтверждение. Проверки при настройке вызывают тот же механизм в изолированном тестовом портфеле; это специально созданные граничные условия, а не рыночная статистика. Backtest проверяет рецепт без лимитов, paper replay применяет лимиты. Потери ограничивают новые покупки, но не гарантируют потолок убытка открытой позиции.",
    ),
    dict(
        id="data",
        title="Where historical prices come from",
        route="/tests",
        keywords="historical source binance candles data real prices откуда данные истор реаль свеч котиров",
        body="The server fetches completed OHLCV candles over HTTPS from Binance Spot: data-api.binance.vision/api/v3/klines. Supported pairs: SOL/USDC, BTC/USDC, ETH/USDC; intervals: 1h, 4h, 1d. Every snapshot records symbol, UTC period, fetch time, source endpoint and content hash. The server rejects missing, overlapping, invalid or unfinished candles. It never substitutes generated prices when the provider fails. Use Download candles to inspect the exact stored rows. A hash proves consistency of stored data, not that an exchange independently signed it. Source: https://github.com/binance/binance-spot-api-docs/blob/master/faqs/market_data_only.md",
        ru="Источник — завершённые OHLCV-свечи Binance Spot, полученные сервером по HTTPS. Сохраняются пара, UTC-период, время получения, адрес источника и хеш. Пропуски, некорректные и незакрытые свечи отклоняются; при сбое API вымышленных цен нет. Download candles выгружает именно использованный набор. Хеш подтверждает неизменность сохранённых данных, но не является подписью биржи.",
    ),
    dict(
        id="backtests",
        title="Historical backtests and baseline",
        route="/tests",
        keywords="backtest tests baseline return бэктест бектест тест доход baseline",
        body="Onboarding downloads 384 closed candles: three consecutive 96-candle backtests, then a separate 96-candle holdout. Returns are computed by running the chosen signal rules on each recorded period, with configured fees and slippage. Signals use prior closes and paper fills use the current close. No intrabar liquidity or order-book model is used. All three onboarding runs are stored. The first period is the pinned deployment baseline. It exists before the agent's first fill because it is a prior strategy test, not the agent's earned return. A passed policy check does not mean a profitable strategy. Downloads contain calculated trades, configuration, source snapshot and signed result.",
        ru="Настройка использует 384 закрытые свечи: три backtest-периода по 96 свечей и отдельный период из 96 свечей для paper replay. Доходность вычисляется по сигналам выбранного рецепта с комиссиями и проскальзыванием. Все три прогона сохраняются. Первый служит базой сравнения после запуска. Поэтому backtest виден сразу после создания: это предварительный тест, не заработок нового агента.",
    ),
    dict(
        id="replay",
        title="Replay the next market period",
        route="/monitoring",
        keywords="advance bars replay simulate monitoring свеч проигр монитор 24 исполн",
        body="A bar is one recorded candle for the selected timeframe. Replay next 24 candles processes up to 24 historical observations: 24 hours at 1h, 4 days at 4h, or 24 days at 1d. It does not wait for future prices or send exchange orders. The endpoint evaluates signals, applies guardrails, records permitted paper fills and pauses at a human approval request. A deployment has 96 held-out candles; its progress persists and requests with stale steps are rejected. Creating an agent does not advance the replay. Monitoring shows progress and approvals; the execution log shows every recorded decision.",
        ru="Bar — одна свеча выбранного интервала. Проиграть 24 свечи — обработать 24 часа при 1h, 4 дня при 4h или 24 дня при 1d. Это ускоренный расчёт по истории, не ожидание будущих цен и не реальные ордера. Применяются сигналы и guardrails, сохраняются paper-сделки; при необходимости подтверждения прогон останавливается. Всего 96 свечей. Само создание агента прогон не запускает.",
    ),
    dict(
        id="performance",
        title="PnL, charts and a new agent",
        route="/performance",
        keywords="performance pnl chart new zero empty graph результат прибыль график новый ноль",
        body="Paper PnL equals current cash plus marked position value minus starting capital; fees are included. Return is PnL divided by starting capital. Drawdown is the largest peak-to-trough equity loss. Only verified stored paper fills contribute to execution results. A new deployment starts at step 0 with no fills, no earned return and no paper curve. The dashed backtest curve comes from a pre-deployment test. The solid paper curve appears after replay; curves compare normalized progress across different dates, not simultaneous returns. Check source dates and the execution log before interpreting a chart. The system never automatically advances a new deployment.",
        ru="PnL = деньги + стоимость позиции − начальный капитал, с учётом комиссий. Доходность = PnL / начальный капитал. У нового агента шаг 0, сделок и заработанной доходности нет. Пунктир на графике — предварительный backtest. Сплошная линия появляется после paper replay; линии относятся к разным датам и сравнивают ход прогона. Источник результата можно проверить в журнале сделок.",
    ),
    dict(
        id="health",
        title="Health score and degradation alerts",
        route="/degradation",
        keywords="health score degradation alert watch здоровье оценк деградац сигнал",
        body="Health is a diagnostic score, not a prediction. It requires a baseline and at least five closed trades. Weights: paper performance 30%, drawdown 25%, backtest/paper gap 20%, verified execution 15%, recent winning exits 10%. Component formulas are shown on the strategy page; no total score is displayed with insufficient observations. Degradation alerts record actual detected threshold breaches. No alert means no recorded breach in the available sample, not proof of safety. Alerts can be acknowledged without deleting evidence.",
        ru="Health — диагностическая оценка, не прогноз. Нужны базовый тест и хотя бы 5 закрытых сделок. Вес доходности 30%, просадки 25%, расхождения с backtest 20%, проверенного исполнения 15%, доли последних прибыльных выходов 10%. Если данных мало, общая оценка отсутствует. Отсутствие предупреждений не доказывает безопасность.",
    ),
    dict(
        id="approvals",
        title="Approve a paper trade",
        route="/monitoring",
        keywords="approve approval confirm human разреш подтверж челов",
        body="Orders above your approval threshold wait for an authenticated owner decision. Inspect side, quantity, price and policy snapshot. Approving rechecks the current version, agent state and limits; a stale or unsafe order is rejected. A paused or stopped agent cannot execute pending trades. Copilot can explain and open the review page but cannot approve, execute, deploy or publish on your behalf.",
        ru="Сделка выше порога ожидает решения владельца. Проверьте направление, объём, цену и лимиты. После подтверждения система заново проверяет версию, состояние агента и ограничения. Copilot может объяснить или открыть экран, но не подтверждает сделки и не запускает их самостоятельно.",
    ),
    dict(
        id="publication",
        title="Publish an agent and its strategy evidence",
        route="/developers",
        keywords="publish publication marketplace copy clone опубликов публикац маркетплейс копир",
        body="Open Developer studio, choose an agent and select Publish agent. The disclosure panel explains which identity, strategy versions, historical tests, performance, trades and proofs become public. Publication lists the agent identity, versioned recipe and its track record; it does not authorize anyone to control your agent. A visitor chooses Test this agent with my limits, gets a fresh private draft from the selected version, sets personal limits, reruns tests and reviews deployment. No capital, keys, approvals or trade history are transferred. Unpublish removes public access while your private records remain.",
        ru="Откройте Developer studio → Publish agent. Перед публикацией показано, какие настройки, версии, тесты, сделки и доказательства станут публичными. Посетитель выбирает Test this agent with my limits и получает собственный черновик: капитал, ключи и сделки автора не копируются. Его агент создаётся только после собственных тестов и review. Unpublish убирает публичный доступ.",
    ),
    dict(
        id="proofs",
        title="What a proof verifies",
        route="/proofs",
        keywords="proof receipt verify signature доказ квитанц подпис провер",
        body="A trading proof binds a paper fill to its strategy version, policy decision, ledger readback and recorded market-data snapshot. Verify checks the hash, signing identity and receipt chain. Download the JSON to verify independently against a separately trusted Tracy public key. It proves what Tracy recorded, not exchange execution, a blockchain transaction or profitability. The operator controls the signing key; public-key pinning matters.",
        ru="Proof связывает paper-сделку с версией стратегии, решением policy, записью в журнале и набором свечей. Проверяются хеш, подпись и цепочка. Это доказательство записи Tracy, а не реальной биржевой или блокчейн-транзакции. JSON можно проверить независимо с доверенным публичным ключом.",
    ),
    dict(
        id="security",
        title="Accounts, privacy and Copilot",
        route="/security",
        keywords="security account privacy key copilot assistant chat settings аккаунт приват ключ чат помощ настрой",
        body="Accounts isolate private agents, strategies, plans and receipts. Use Settings for passwords, recovery codes and API keys. Never paste secrets into chat. Copilot uses this handbook and an owner-scoped summary of the selected page; it does not receive signing keys, passwords or other users' private data. If an AI provider is configured, opt in using Use Gemini or Use OpenAI. Your message, recent conversation, draft settings and the selected page summary are sent to that provider. Google free-tier data terms may allow content to improve its products. Quota errors leave settings unchanged; switch off AI to use reference mode. Without a provider, the clearly labeled built-in mode retrieves reference answers and recognizes supported form commands; it cannot hold an unrestricted AI conversation. Form changes are previewed and require Apply to draft, followed by tests and review.",
        ru="Личные агенты и данные разделены по аккаунтам. Не отправляйте секреты в чат. Copilot использует справочник и разрешённые данные текущей страницы. Включите Use Gemini или Use OpenAI для AI-ответов. Провайдеру передаются сообщение, недавний диалог, черновик и краткие данные экрана — без ключей и паролей. У бесплатного Gemini есть квоты и условия использования контента для улучшения продуктов Google. Если квота исчерпана, выключите AI и используйте справку; настройки при ошибке не меняются. Без провайдера работает явно обозначенный режим справки и поддерживаемых команд. Настройки применяются только через Apply to draft, затем нужны тесты и review.",
    ),
]
BY_ID = {a["id"]: a for a in ARTICLES}


def topic_for(path):
    if path.startswith("/help/"):
        return path.split("/")[2] if path.split("/")[2] in BY_ID else "start"
    if path in ("/agents/new", "/strategies/new"):
        return "intent"
    return {
        "/tests": "backtests",
        "/infrastructure": "guardrails",
        "/monitoring": "replay",
        "/performance": "performance",
        "/degradation": "health",
        "/proofs": "proofs",
        "/security": "security",
        "/": "start",
        "/explore": "start",
        "/leaderboard": "leaderboard",
        "/compare": "leaderboard",
        "/developers": "publication",
        "/strategies": "publication",
    }.get(path, "performance" if path.startswith("/strategies/") else "start")


def relevant(message, path):
    text = message.lower()
    scores = [(sum(len(k) for k in a["keywords"].split() if k in text), a) for a in ARTICLES]
    scores.sort(key=lambda item: item[0], reverse=True)
    selected = [a for score, a in scores if score > 0][:3]
    current = BY_ID[topic_for(path.split("?")[0])]
    if current not in selected:
        selected.append(current)
    return selected[:3]
