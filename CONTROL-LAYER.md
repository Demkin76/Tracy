# Tracy 2.0 — control layer для AI-агентов

Tracy принимает подписанное намерение агента, проверяет выданную владельцем задачу и policy, исполняет разрешённое действие через серверный адаптер, отдельно читает результат и выпускает подписанное доказательство. Главный экран — /control. Каталог и старые Devnet-рецепты сохранены как дополнительные функции.

## Как попробовать подготовленную демо

Из корня проекта в PowerShell:

~~~powershell
.\Start-ControlDemo.ps1 -SkipBuild
~~~

Открыть http://127.0.0.1:8000/control. Вход: email и пароль из локального data/tracy-owner.json. Не передавать этот файл агенту. На новом checkout сначала запустить без -SkipBuild: скрипт установит зависимости при отсутствии .venv, создаст ключи и локального владельца, соберёт интерфейс.

Оба сервиса работают в фоне: Tracy :8000, локальный симулятор :8011. Логи — data/control-server.err.log и data/control-provider.err.log. Повторный запуск сохраняет историю. Для новой серии из четырёх примеров:
~~~powershell
.\Start-ControlDemo.ps1 -SkipBuild -NewScenario
~~~

Команда создаёт новую задачу на 7 дней и новые намерения. Запускать её один раз перед показом, а не постоянно: policy ограничивает частоту. Она восстанавливает демо-policy агента tracy_control_demo; собственные настройки создавайте у другого агента.

В Control center выбрать tracy_control_demo. В Human approvals открыть запись:
1. Сверить intent: действие, ресурс, параметры, задача и причина.
2. Сверить policy, разрешённую цель и лимиты.
3. Нажать Approve либо Deny. Подтверждение привязано к хешу именно этого intent и версии policy.
4. После Approve подождать до 5–10 секунд. VERIFIED означает успешный отдельный readback.
5. Нажать Verify evidence now, скачать доказательство или Export audit в настройках агента.

В примерах:
- database.insert действительно добавляет строку в отдельную локальную SQLite после подтверждения.
- http.invoke автоматически разрешён policy; локальный провайдер сохраняет операцию без списания денег.
- github.pull_request требует подтверждения и создаёт объект draft PR в локальном симуляторе. Это не PR на github.com.
- попытка передать произвольный SQL блокируется до исполнения.

Остановить: .\Stop-ControlDemo.ps1. Для применения изменений Python остановить и заново запустить сервисы. Не перезапускать ради повтора операции: сохраняется intent_id, а UNCERTAIN сверяется через readback.

## Подключение своего агента

В Control center зарегистрировать identity, скачать agent key, сохранить policy, затем выдать задачу с purpose, сроком и списком действий/ресурсов. Пустая policy запрещает всё. Скачанный ключ подписывает намерения; это не ключ execution-кошелька.

~~~python
from sdk.tracy import AgentIdentity, Tracy

tracy = Tracy("http://127.0.0.1:8000", task_id="TASK_ID_FROM_UI")
agent = tracy.protect(AgentIdentity.from_file("agent-key.json"))
try:
    intent = agent.intent(
        "database.insert", "demo-records",
        {"record": {"message": "Task completed"}},
        request_id="invoice-123-record-v1",
        reason="Store the approved task result",
    )
    result = agent.wait(intent["intent_id"])
    print(result["status"])  # Может вернуть AWAITING_APPROVAL или UNCERTAIN.
finally:
    tracy.close()
~~~

Повтор одной логической операции должен использовать тот же request_id и те же смысловые поля. Tracy вернёт существующий intent; изменение параметров при том же ID вернёт 409. Новый ID — новая операция. После рестарта бот должен сохранить ID своей операции.

Пример CLI — examples/control_agent.py; переменные TRACY_BASE_URL, TRACY_AGENT_KEY_FILE, TRACY_TASK_ID, TRACY_REQUEST_ID (стабильный), опционально TRACY_RESOURCE_ID.

protect принимает AgentIdentity и возвращает защищённый интерфейс инструментов. Он не перехватывает все вызовы Python и не изолирует произвольный объект агента автоматически. В agent framework заменить чувствительные инструменты на Tracy tools:

~~~python
from sdk.tracy.langchain import tools
guarded_tools = tools(agent, [{
    "name": "record_result",
    "description": "Request a controlled database write",
    "action": "database.insert",
    "resource_id": "demo-records",
}])
# Передать guarded_tools вашему LangChain/LangGraph agent.
# Не оставлять ему параллельно исходный инструмент записи.
~~~

Зависимости интеграции: uv sync --locked --extra dev --extra frameworks. Проверено через настоящий StructuredTool.invoke; вызов LLM для проверки не требуется.

## MCP и API

MCP stdio: python -m sdk.tracy.mcp. Настройка клиента:
~~~json
{
  "mcpServers": {
    "tracy": {
      "command": "C:/path/to/tracy/.venv/Scripts/python.exe",
      "args": ["-m", "sdk.tracy.mcp"],
      "env": {
        "TRACY_BASE_URL": "http://127.0.0.1:8000",
        "TRACY_AGENT_KEY_FILE": "C:/agent/agent-key.json",
        "TRACY_TASK_ID": "TASK_ID_FROM_UI"
      }
    }
  }
}
~~~

Пакет должен быть установлен в выбранной Python-среде. Сервер поддерживает протокол MCP 2025-11-25; инструменты tracy_intent и tracy_status. Инструментов approve, смены policy и получения серверных ключей нет.

API-документация: http://127.0.0.1:8000/docs.
- POST /v2/agents — владелец регистрирует публичный ключ.
- GET/PUT /v2/agents/{id}/policy — версия policy и optimistic concurrency.
- POST /v2/tasks, POST /v2/tasks/{id}/revoke — выдача/отзыв задачи.
- POST /v2/intents — подписанный агентом intent.
- POST /v2/intents/lookup — подписанный запрос статуса.
- GET /v2/intents и /v2/intents/{id} — приватная история владельца.
- POST /v2/intents/{id}/decision — browser session + CSRF, точный hash/version.
- GET /v2/intents/{id}/verify — подписи, цепочка и свежий readback.
- GET /v2/agents/{id}/export — receipts и журнал решений.

Агенту достаточно intent signing key и task_id. Owner API key может управлять конфигурацией и не должен попадать к агенту. Human approval отвергает Bearer-токены; браузерная сессия владельца также должна быть недоступна агенту. Проверка cookie не доказывает физическое присутствие человека, если его сессию скомпрометировали.

## Исполнение и доказательства

Policy проверяет точное действие, ресурс, target whitelist, максимальные единицы за операцию и за сутки UTC. Дополнительно: статус агента/платформы, выданную задачу, TTL, число запросов в минуту, серию отказов, новый target и требование approval. Это объяснимые правила обнаружения отклонений, а не ML-анализ смысла задачи.

Резервирование лимита атомарно в БД. Перед подготовкой и непосредственно перед dispatch заново проверяются task, stop, policy version и привязка ресурса. Approval истекает и не переносится на другую policy. Stop не отменяет уже отправленную внешнюю операцию.

Состояния: AWAITING_APPROVAL → QUEUED → DISPATCHED → VERIFIED.
Отказы: REJECTED (не исполнялось), FAILED (смотреть evidence), UNCERTAIN (результат пока не доказан).
При неизвестном результате Tracy не отправляет действие повторно, удерживает резерв и делает readback с backoff. При доказанном несовпадении FAILED резерв также удерживается. Это сознательная граница доступности: сбой между записью DISPATCHED и сетевой отправкой может оставить операцию UNCERTAIN без автоматического повтора. Для ручного разрешения нужна проверка внешней системы, а не новый request_id.

Receipt tracy.receipt/2 связывает:
- подписанный intent и публичный ключ агента;
- задачу, снимок policy, контекст решения и approval;
- хеш конфигурации адаптера, execution result и readback evidence;
- подпись Tracy, последовательность и предыдущий hash.

Подписи и цепочки receipt/audit проверяются офлайн:
~~~powershell
.\.venv\Scripts\python.exe -m scripts.verify_control audit-bundle.json --public-key TRUSTED_TRACY_PUBLIC_KEY
~~~
Ключ доверия нужно получить и закрепить отдельно, не просто принять из скачанного bundle. Для обнаружения удаления хвоста истории нужен сохранённый checkpoint последнего hash/sequence. Хеш-цепочка сама по себе не доказывает полноту истории. Подпись доказывает, что запись выпустил владелец ключа Tracy; истинность внешнего результата требует readback и доверия к источнику. БД и ключ оператора — часть доверенной инфраструктуры, не децентрализованное доказательство.

## Адаптеры и ресурсы

Оператор сервера задаёт data/control-resources.json (POA_CONTROL_RESOURCES_PATH). Пользователь/агент не может загрузить Python-код адаптера или произвольный URL через API. Ресурс содержит id, kind, label, owner_ids. Привязка к владельцу обязательна; "*" допустима только для намеренно общего ресурса.

| Ресурс | Действие и ограничения | Независимая сверка |
| --- | --- | --- |
| solana | solana.transfer, нативный SOL, Devnet, серверный signer | RPC: tx, отправитель, получатель, сумма, memo |
| database | database.insert, фиксированная таблица tracy_records, отдельная SQLite | отдельное read-only подключение, hash и точный payload |
| github | github.pull_request, фиксированный repo, существующие ветки, pinned head_sha, draft | GET PR: repo, refs, SHA, title/body и binding marker |
| http | http.invoke, фиксированный URL, поля и стоимость | GET /operations/{intent_id}, hash, params, status |
| plugin | оператор устанавливает подкласс Adapter | обязательный контракт verify конкретной системы |

Для настоящего GitHub: kind github, base_url https://api.github.com, repository OWNER/REPO, token_env TRACY_GITHUB_TOKEN, owner_ids [OWNER_USER_ID]. Токен хранить только на сервере; fine-grained permissions для чтения commits и создания PR только выбранного репозитория. Код не пушит ветки, не мерджит PR, не выполняет workflows от имени агента. Изменение ветки между prepare и созданием PR возможно на стороне GitHub: readback обнаружит несовпадение, но не отменит уже созданный draft. Для строгого запрета такой гонки оператор должен защитить исходную ветку от изменений.

HTTP-адаптер — контракт шлюза, не универсальная совместимость с любым платным API:
- POST /execute с Idempotency-Key, intent_id, request_hash, params;
- GET /operations/{intent_id} возвращает request_hash, params, status completed/pending/running;
- URL/пути и схема параметров задаются оператором, redirects запрещены;
- стоимость units_per_call фиксируется оператором. Реальную переменную стоимость/счёт надо проверять отдельным адаптером, текущий лимит не сверяет invoice провайдера.

Реальные HTTP-ресурсы требуют HTTPS. local_test:true разрешён только для явно настроенного loopback симулятора. Секрет берётся из указанной env-переменной либо server-only data/control-credentials.json (POA_CONTROL_CREDENTIALS_PATH); агент не получает ни токен, ни имя переменной через список ресурсов.

Расширение: kind plugin, adapter "your_package.module:YourAdapter". Класс наследует backend.control.connectors.Adapter; validate возвращает (точная_цель, целые_единицы); prepare не делает побочных действий; execute вызывается максимум один раз; verify отдельно читает систему и возвращает verified/pending/mismatch/failed/unavailable с reason/source. Доказанный failed должен означать отсутствие эффекта, иначе бюджет нельзя освобождать. PreflightRejected допустим только при доказанном отказе до отправки. Не добавлять секреты в prepared/result/evidence, которые могут попасть в экспорт; signed Solana bytes специально остаются приватными в БД. Установка плагина — доверенная операция администратора сервера, не marketplace пользовательского кода.

## Граница защиты и развёртывание

Гарантия «агент не обходит Tracy» действует только для доступа, которым владеет Tracy:
1. Execution wallet seed, API/GitHub токены, DB-доступ и ключ подписи receipts хранятся у сервера.
2. У процесса агента только отдельный intent key и идентификатор задачи.
3. Агент работает под другим OS user/в контейнере/на другом узле; у него нет доступа к Tracy .env, data/, Docker socket, owner cookies и файловой системе сервера.
4. Чувствительный внешний сервис не должен принимать другой доступ, доступный агенту. При необходимости сеть агента ограничивается Tracy и необходимыми LLM endpoint.
5. Для своего wallet/KMS signer реализовать серверный адаптер; браузерный wallet с ключом, доступным агенту, эту границу не обеспечивает.

Запуск агента на том же Windows-пользователе с доступом к репозиторию подходит для демо, но не является изоляцией. protect не создаёт OS sandbox. Tracy не может запретить агенту использовать чужие, отдельно выданные ему полномочия.

Сервер запускается одним worker с блокировкой БД и durable reconciliation. Dockerfile/compose.yaml — основа серверного контейнера, не готовая изоляция произвольных агентов. В production добавить HTTPS, управление секретами и ротацию ключей, внешний мониторинг, резервное копирование и проверенный recovery; провести независимый security review. Не выдавать этой локальной демо доступ к mainnet или production базе.

Бэкап:
~~~powershell
.\.venv\Scripts\python.exe -m scripts.backup --out data/backups/tracy-control-backup.sqlite3
~~~
Бэкап проверяет подписи старых и новых receipts и audit chain. Также отдельно сохранить соответствующие ключи и конфигурацию ресурсов. Он не копирует внешние БД и симулятор провайдера; для согласованной полной копии локального демо остановить сервисы и сохранить все файлы data плюс .env в закрытом хранилище.

## Что ещё не заявляется как готовое

SPL/USDC, swaps, произвольный SQL, произвольный API, mainnet, custody production-средств, HA с несколькими workers и автоматическая изоляция любого AI framework не реализованы. Для них нужны отдельные проверенные адаптеры/эксплуатационная инфраструктура. Подключения GitHub/API в подготовленной демо проверены на локальном сервисе по вашему выбору; реальные интеграции потребуют настройки и отдельной проверки.

Спецификации интеграций: [GitHub Pull Requests REST](https://docs.github.com/en/rest/pulls/pulls), [fine-grained permissions](https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens), [MCP lifecycle 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle), [MCP tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools), [LangChain StructuredTool](https://reference.langchain.com/python/langchain-core/tools/structured/StructuredTool/from_function).
