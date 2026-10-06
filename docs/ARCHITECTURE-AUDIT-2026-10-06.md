# Аудит соответствия Tracy целевой архитектуре

Дата проверки: 06.10.2026 18:17:06 CEST. Основание: предоставленный пользователем документ «Целевая техническая архитектура Tracy», включая все 34 пункта checklist.

**Вывод: соответствие частичное.** В Tracy реализован работающий MVP детерминированных paper-агентов с ограниченным статистическим обучением, immutable snapshots, независимыми клонами и Devnet memo-доказательствами. Полный цикл Decision → Outcome → Attribution → Feedback → новая APR-policy пока не реализован.

Это проверка backend, схем БД, execution-path и тестов, а не оценка наличия экранов. Код приложения и работающий эксперимент в ходе аудита не изменялись; создан только этот отчёт. Проверка входа создавала временную сессию, затем выполнялся logout.

## Метод и границы проверки

- Сверены SHA-256 **85 файлов** backend, собранного frontend и origin-wrapper на AWS с локальными файлами: **расхождений нет**.
- Повторно выполнен весь Python suite: **187 passed**, одно предупреждение Starlette/AnyIO о deprecated API. Unit tests используют fixtures; это не рыночные результаты.
- Прочитаны публичные и owner-scoped API работающего сайта. Это отдельная проверка фактического состояния, не подмена её unit fixtures.
- Дополнительно в изолированной временной БД воспроизведён пробел global execution switch. Никаких изменений рисков/состояния облачного агента для этого не выполнялось.
- Статусы: DONE — пункт работает в указанном MVP scope; PARTIAL — реализована часть, но контракт документа не соблюдён полностью; NOT IMPLEMENTED — требуемого компонента нет. MOCK означал бы интерфейс/заглушку без работающего механизма. **MOCK здесь не присвоен: paper simulation честно обозначена и сама по себе не является mock-данными.**
- Количество пунктов: 8 DONE, 20 PARTIAL, 6 NOT IMPLEMENTED. Это не процент готовности: Attribution и Outcome намного значимее некоторых отдельных UI-функций.

## Основные расхождения

### 1. APR сейчас означает другую структуру

Документ требует строки `condition/action/probability/reason`, затем `expected_outcome/evaluation_horizon/invalidation`. Сейчас Strategy APR — подписанный blueprint, Agent APR — три arm со статистикой Beta(alpha,beta), активный arm и cutoff данных. Названия APR совпадают, контракт данных — нет. Отношение alpha/(alpha+beta) не является калиброванной вероятностью будущей прибыли и не сохраняется как probability отдельного решения.

### 2. Attribution отсутствует, feedback использует знак PnL

[learn()](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/engine.py:50) делает буквально `alpha += 1`, если `pnl > 0`, иначе `beta += 1`. В целевом документе именно такой прямой подход «profit → reward, loss → punish» отвергнут. Издержки учтены в PnL, но причины результата не разделяются. Успешный holdout gate не заменяет Attribution Engine.

Смена активного arm требует минимум 3 training exits для кандидата, минимум 5 validation exits для каждой сравниваемой policy, улучшения return >0.05 п.п., проверки drawdown и ручной активации. Это gate активации новой policy, а не фильтр пригодности каждого outcome для learning. Предложенные в документе 20 samples — пример, но универсальной feedback eligibility/minimum-sample модели всё равно нет.

### 3. Два отдельных execution/guardrail контура

`strategies + trading` используют TradingService.evaluate и очередь approvals. `adaptive` вызывает собственный engine.step и создаёт fills внутри этого вызова. Ограничения действуют, но общей обязательной границы Decision → Authorization → Execution нет.

**Подтверждённый пробел управления:** при `execution_enabled=False` API Adaptive forward возвращает **201 / RUNNING**, если включён reconciler и имеется исторический run. В обычном trading этот флаг запрещает исполнение. Точечная локальная проверка также запустила forward без вызова activate/review; backend проверяет наличие отчёта и revision, а не подтверждение review. Это не означает активацию непроверенного candidate: baseline остаётся активным, но обещание «review перед запуском» на этом endpoint не обеспечено.

В Adaptive превышение approval threshold блокирует entry; запроса человеку не создаётся. Reduce-only exits могут превышать entry limits — это явное текущее правило, описанное в Strategy APR, а не случайный обход. Лимиты потерь проверяются при наблюдениях и не гарантируют цену остановки.

### 4. Замкнутого автоматического цикла обучения пока нет

Рабочий путь сейчас:

```text
supported rules → historical training → frozen holdout → manual activation
→ 24h forward with frozen active arm → collect closed-trade counts
→ save next state revision → another reviewed experiment
```

В forward счётчики обновляются по закрытым сделкам, в основной Agent state они переносятся при завершении run. Отдельного horizon-based Outcome worker, причинной attribution и автоматического принятия новой policy на следующем decision нет.

### 5. Strategy / Agent / Marketplace ещё не приведены к единой модели

Старые стратегии требуют agent_id; Adaptive создаёт собственные Strategy snapshots при создании инстанса. При импорте обычной стратегии в Adaptive исходные Strategy ID/version не сохраняются как связь происхождения. Независимость cloned Agent state уже реализована, однако этого недостаточно для целевой модели «одна StrategyVersion → множество Agents → общий creator lineage и cohort metrics».

Каталоги стратегий и Bundle отдельные. Нет purchase/licensing/revenue accounting. Публичный Bundle уже работает, но является бесплатным snapshot, а не полноценным продаваемым активом со всеми полями документа.

### 6. Граница Pine и Devnet

Pine поддерживается только в виде одного строгого SMA шаблона. Gemini редактирует параметры поддерживаемых runners, но не генерирует полноценный Pine/произвольную стратегию. В Devnet выполняются реальные memo-транзакции, однако торговля агента остаётся виртуальной по реальным Binance ценам; Devnet DEX execution не реализован.

## Все пункты checklist

| № | Компонент | Статус | Фактическое состояние и недостающее | Доказательство |
|---|---|---|---|---|
| 1 | Strategy entity + versioning | **PARTIAL** | Есть strategies/strategy_versions с запретом UPDATE/DELETE, но Strategy требует agent_id. Adaptive использует отдельные adaptive_strategies без общей цепочки версий и source_type; fork не сохраняет исходные strategy_id/version. | [service.py:70](/Users/hzneznaju/PycharmProjects/Tracy/backend/strategies/service.py:70); [service.py:126](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/service.py:126) |
| 2 | Pine Script import | **PARTIAL** | Реальный строгий импорт одного Pine v6 SMA crossover шаблона. Произвольные Pine, RSI, inputs, security(), stops и shorting отвергаются. | [pine.py:20](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/pine.py:20) |
| 3 | Pine → deterministic representation | **PARTIAL** | Поддерживаемый шаблон превращается в Program(sma_cross); универсального компилятора/AST нет. | [pine.py:45](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/pine.py:45) |
| 4 | AI Strategy Builder | **PARTIAL** | Gemini отвечает, задаёт вопросы и предлагает валидируемые изменения полей готового runner. Произвольную торговую программу и Pine не создаёт. | [service.py:18](/Users/hzneznaju/PycharmProjects/Tracy/backend/assistance/service.py:18); [service.py:432](/Users/hzneznaju/PycharmProjects/Tracy/backend/assistance/service.py:432) |
| 5 | Pine generation | **NOT IMPLEMENTED** | Есть статический EXAMPLE для импорта. Генерации Pine из идеи или внутренней стратегии нет. | [pine.py:9](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/pine.py:9); [service.py:432](/Users/hzneznaju/PycharmProjects/Tracy/backend/assistance/service.py:432) |
| 6 | Strategy graph | **NOT IMPLEMENTED** | Нет представления стратегии графом условий/действий или редактора графа. График equity не является strategy graph. | [AdaptivePages.tsx:222](/Users/hzneznaju/PycharmProjects/Tracy/frontend/src/AdaptivePages.tsx:222) |
| 7 | Backtesting | **DONE** | Исполняемые симуляции на сохранённых реальных свечах; комиссии, slippage, разделённые train/holdout, baseline/incumbent/candidate. DONE для поддерживаемых программ, не для любого Pine. | [engine.py:182](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/engine.py:182); [provider.py:22](/Users/hzneznaju/PycharmProjects/Tracy/backend/market_data/provider.py:22) |
| 8 | Strategy APR generation | **PARTIAL** | strategy-apr/1 — подписанный blueprint правил/риска/издержек. Таблицы condition/action/probability/reason из целевой архитектуры нет. | [service.py:89](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/service.py:89) |
| 9 | Immutable Strategy APR | **DONE** | Сохраняется подписанный snapshot, хеш проверяется при чтении; UPDATE/DELETE запрещены DB-триггерами. Это защита текущего формата, не наличие целевой APR-таблицы. | [service.py:57](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/service.py:57); [migrations.py:34](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/migrations.py:34) |
| 10 | Agent entity | **PARTIAL** | Есть отдельный adaptive_agents с owner/strategy/revision, но runtime-статус находится в forward-run. Общей модели CREATED/PAPER/DEVNET/LIVE/PAUSED/STOPPED нет. | [migrations.py:6](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/migrations.py:6); [models.py:24](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/models.py:24) |
| 11 | Strategy APR → Agent APR cloning | **PARTIAL** | Agent получает отдельные исходные arms/счётчики из blueprint. Это не копирование единой APR-таблицы с сохранённой идентичностью StrategyVersion. | [service.py:89](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/service.py:89); [engine.py:23](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/engine.py:23) |
| 12 | Agent APR persistence | **DONE** | Подписанные состояния хранятся в adaptive_states по (agent_id, revision), проверяются при чтении, старые записи не перезаписываются. | [service.py:38](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/service.py:38); [service.py:80](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/service.py:80) |
| 13 | Scheduler | **PARTIAL** | Постоянный серверный Reconciler обрабатывает next_tick; после перезапуска продолжает сохранённые runs. Adaptive привязан к 1h/4h/1d и 24-часовому сравнению; произвольного интервала 5m и PRICE/BLOCK/EVENT/WEBHOOK-триггеров нет. | [runtime.py:53](/Users/hzneznaju/PycharmProjects/Tracy/backend/platform/runtime.py:53); [forward.py:266](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/forward.py:266); [provider.py:13](/Users/hzneznaju/PycharmProjects/Tracy/backend/market_data/provider.py:13) |
| 14 | EXEC Agent | **PARTIAL** | Детерминированный executor использует историю рынка, portfolio и активный arm. Нет общего Decision-контракта с confidence, expected_outcome и evaluation_horizon; LLM не принимает торговые решения. | [engine.py:88](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/engine.py:88) |
| 15 | Market data input | **DONE** | Реальные Binance candles и bid/ask с размером верхнего уровня стакана; provenance/hash и отказ при недоступных данных. Поддерживаются три пары и три таймфрейма. | [provider.py:13](/Users/hzneznaju/PycharmProjects/Tracy/backend/market_data/provider.py:13); [forward.py:23](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/forward.py:23) |
| 16 | Guardrail Engine | **PARTIAL** | Проверки риска реально исполняются, но в двух разных реализациях. Adaptive не использует общий TradingService.evaluate, не проверяет execution_enabled и не возвращает отдельный REQUIRE_APPROVAL. Spot/одна позиция ограничены схемой, универсальных protocol/leverage правил нет. | [service.py:50](/Users/hzneznaju/PycharmProjects/Tracy/backend/trading/service.py:50); [engine.py:108](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/engine.py:108); [models.py:48](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/models.py:48) |
| 17 | Human approval | **PARTIAL** | В обычном paper trading есть очередь approval с привязкой к intent/version, expiry и browser CSRF. В Adaptive порог лишь ограничивает вход; очереди одобрения сделок нет. Review активации arm — другой механизм. | [service.py:403](/Users/hzneznaju/PycharmProjects/Tracy/backend/trading/service.py:403); [routes.py:160](/Users/hzneznaju/PycharmProjects/Tracy/backend/strategies/routes.py:160); [engine.py:137](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/engine.py:137) |
| 18 | Paper execution | **DONE** | Реальный paper ledger и расчёт fills/PnL; forward исполняет виртуальные сделки по текущим bid/ask с заданными издержками. Биржевые ордера не отправляются. | [engine.py:129](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/engine.py:129); [forward.py:204](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/forward.py:204) |
| 19 | Solana Devnet execution | **PARTIAL** | Есть настоящие Devnet memo-транзакции для Bundle и отдельный legacy-код SOL transfer. Адаптивная стратегия не покупает/продаёт токены через Devnet DEX. Именно торговый DEVNET adapter отсутствует. | [anchors.py:12](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/anchors.py:12); [solana.py:132](/Users/hzneznaju/PycharmProjects/Tracy/backend/blockchain/solana.py:132) |
| 20 | Decision persistence | **DONE** | Решения сохраняются в отчётах экспериментов и состоянии forward; observation включает agent_decision/baseline_decision в подписанную цепочку. Общего decision_id для будущего Outcome пока нет. | [engine.py:168](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/engine.py:168); [forward.py:255](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/forward.py:255) |
| 21 | Proof of Action | **PARTIAL** | Подписанные immutable-отчёты, версии и цепочки forward работают. Нет полного единого INTENT→DECISION→AUTHORIZATION→EXECUTION с целевыми APR probability/reason/expected/horizon и биржевой tx для каждого решения. | [service.py:20](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/service.py:20); [forward.py:94](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/forward.py:94) |
| 22 | Outcome worker | **NOT IMPLEMENTED** | Нет worker, который планирует оценку отдельного Decision по его horizon и создаёт Outcome. PnL на закрытии позиции и завершение 24h-run эту функцию не заменяют. | [forward.py:237](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/forward.py:237); [runtime.py:53](/Users/hzneznaju/PycharmProjects/Tracy/backend/platform/runtime.py:53) |
| 23 | Expected outcome / horizon | **NOT IMPLEMENTED** | Нет полей expected_outcome/evaluation_horizon/invalidation в Program/Decision. exit_after_bars задаёт выход из позиции, а не срок проверки прогноза. | [models.py:9](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/models.py:9); [engine.py:168](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/engine.py:168) |
| 24 | Attribution Engine | **NOT IMPLEMENTED** | Нет разделения decision quality / execution / regime / sizing / noise и eligible_for_learning. Обновление зависит от знака net PnL. | [engine.py:50](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/engine.py:50) |
| 25 | Feedback / Learning Signal | **PARTIAL** | Закрытые paper outcomes реально обновляют alpha/beta и net_pnl. Но нет Verified Outcome→Attribution→IGNORE/UPDATE; каждое закрытие обновляет статистику без attribution-фильтра. | [engine.py:50](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/engine.py:50); [engine.py:163](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/engine.py:163) |
| 26 | Agent APR updates | **PARTIAL** | Меняются счётчики трёх заранее заданных arms; выбор нового активного arm требует исторического gate и явной активации. Во время forward активный arm заморожен. Автоматического полного policy-update цикла нет. | [engine.py:203](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/engine.py:203); [service.py:218](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/service.py:218); [forward.py:237](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/forward.py:237) |
| 27 | APR versioning | **PARTIAL** | Append-only подписанные snapshots и номера revision есть. Нет отдельной записи policy change с previous/new, списком outcome IDs, attribution, why и нормализованным diff. | [service.py:80](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/service.py:80); [migrations.py:10](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/migrations.py:10) |
| 28 | Strategy Marketplace | **PARTIAL** | Публикация и публичный каталог стратегий работают. Но это отдельный контур от Bundle; listing привязан к старым стратегиям/агентам, нет единой сущности STRATEGY/BUNDLE listing. | [service.py:349](/Users/hzneznaju/PycharmProjects/Tracy/backend/strategies/service.py:349); [ExchangePages.tsx:116](/Users/hzneznaju/PycharmProjects/Tracy/frontend/src/ExchangePages.tsx:116) |
| 29 | Bundle entity | **PARTIAL** | Есть замороженные strategy/agent APR, риск, версия движка, отчёт и completed-forward evidence. Нет полноценной модели creator/StrategyVersion/price_model/licensing; цена — строка Free devnet preview. | [service.py:242](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/service.py:242) |
| 30 | Bundle Marketplace | **DONE** | Публикация/снятие, публичное чтение и каталог работают для бесплатных Bundle. Единый каталог со стратегиями и платные покупки не включены в этот статус. | [service.py:305](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/service.py:305); [service.py:326](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/service.py:326) |
| 31 | Bundle → independent Agent cloning | **DONE** | Новый agent_id, отдельные состояния, нулевая личная история; learned state копируется, shared mutable APR нет. Можно наследовать опыт или начать только с правил. | [service.py:334](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/service.py:334); [service.py:121](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/service.py:121); [test_adaptive.py:68](/Users/hzneznaju/PycharmProjects/Tracy/tests/test_adaptive.py:68) |
| 32 | Creator attribution | **PARTIAL** | owner_id и source_bundle есть внутри БД. В переносимом Bundle нет явного исходного creator_id; при fork обычной стратегии теряются исходные strategy_id/version. Ключ подписи общий для платформы, не подпись автора. | [migrations.py:17](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/migrations.py:17); [service.py:126](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/service.py:126); [service.py:258](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/service.py:258) |
| 33 | Marketplace metrics | **PARTIAL** | Есть paper performance/сравнение стратегий, replay leaderboard в UI и baseline-vs-candidate внутри эксперимента. Нет cohort-агрегатов по клонам: live decisions, profitable agents %, median return/drawdown, policy updates. | [service.py:9](/Users/hzneznaju/PycharmProjects/Tracy/backend/performance/service.py:9); [ExchangePages.tsx:272](/Users/hzneznaju/PycharmProjects/Tracy/frontend/src/ExchangePages.tsx:272); [service.py:341](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/service.py:341) |
| 34 | Fee accounting | **NOT IMPLEMENTED** | Нет purchases, creator revenue, Tracy fee, платёжного ledger/settlement. fee_bps относится к симуляции торговых издержек, не к монетизации платформы. | [service.py:271](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/service.py:271); [engine.py:152](/Users/hzneznaju/PycharmProjects/Tracy/backend/adaptive/engine.py:152) |

## Что подтверждено в работающем AWS deployment

На момент чтения API (06.10.2026 18:17:06 CEST):

- `ready=true`; `execution=paper`; `mainnet_enabled=false`; фоновой worker и Devnet anchors включены.
- [Агент](https://tracys.online/lab/adaptive_5a4a3bd9ad7e488987cbade19b30c269): revision 3, active arm 2, один исторический experiment.
- [Суточный forward](https://tracys.online/lab/forward/forward_1b1a682473dc471d98ec7e65d552ec4c): **RUNNING**, одна observation, ошибок нет, `proof_valid=true`. Fills: **0 у baseline и 0 у agent**; PnL обоих 0. Это отсутствие выполненных сделок, не доказательство безубыточности. Получено новое наблюдение после запуска фонового worker.
- [Публичный Bundle](https://tracys.online/bundles/bundle_b2bd6afe7b47403f831c5a5af3994cbd): опубликован, API сообщает `anchor.status=CONFIRMED`, `valid=true`. Он был заморожен до окончания forward и содержит **0 completed forward evidence**. Его on-chain memo не доказывает суточный trading track record, которого ещё нет.
- Подтверждённая ранее holdout-оценка: baseline −$8.365596, candidate −$6.846627 при $1,000 виртуального капитала. Это меньший убыток на одном периоде, не прибыльность и не результат текущих суток.
- Шифрование диска, S3 backup/readback, TLS и systemd описаны в [AWS runbook](/Users/hzneznaju/PycharmProjects/Tracy/deploy/aws/README.md:1). Они обеспечивают работу инфраструктуры, но не закрывают отсутствующие архитектурные компоненты.

Evidence-файлы локального аудита: `data/aws-deployment/architecture-audit.json` и `architecture-control-repro.json` (исключены из Git). Прочие пользовательские данные и секреты в этот отчёт не включены.

## Приоритет следующей реализации

1. **Объединить контракты и контроль исполнения.** Strategy/StrategyVersion отдельно от runtime Agent; общий immutable Decision, Authorization и Execution; global execution switch и human approvals должны действовать и в Adaptive. Зафиксировать acceptance tests запрета старта/новых входов при выключении, review exact revision и сохранения reduce-only выхода.
2. **Реализовать целевую APR-схему и версии.** Отделить policy, evidence и counters; добавить condition/action/reason и явно определённую семантику probability, expected_outcome/horizon/invalidation. Сохранять creator/source lineage при fork/clone.
3. **Ввести Outcome worker.** Оценивать decisions по horizon, независимо от факта закрытия позиции; отделять результат сигнала от trade PnL и хранить версии рыночных данных.
4. **Добавить Attribution и Feedback.** Компоненты signal/execution/costs/regime/sizing, uncertainty/abstention и eligibility. Только после этого обновлять policy по достаточной выборке, с lineage и diff, сохраняя holdout и возможность отказа от изменения.
5. **Собрать единый Marketplace.** Типы STRATEGY/BUNDLE, creator, отдельные версии публикаций, проверяемая независимость клонов, агрегаты по подходящим cohort. Затем добавить отдельный fee ledger, не смешивая его с trading fees.
6. **Расширять Builder и execution adapters.** Генерация Pine, более широкий поддерживаемый язык, strategy graph и при необходимости отдельный Devnet trading adapter. Реальные деньги не требуются для закрытия пунктов 1–5.

Текущий deployment пригоден для проверки ограниченного paper-learning MVP. Заявлять, что вся архитектура из документа уже реализована или что агент различает причины торговых результатов и сам улучшает reasoning, пока нельзя.
