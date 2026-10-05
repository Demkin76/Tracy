> Tracy v3 is the current strategy lifecycle MVP. See [TRACY-V3.md](TRACY-V3.md) and [DEMO-V3-90SEC.md](DEMO-V3-90SEC.md). The guide below describes the preserved earlier workflow.

# Tracy: минутная демо control layer

Подготовка: .\Start-ControlDemo.ps1 -SkipBuild -NewScenario. Открыть /control, войти через data/tracy-owner.json. Не показывать пароль или ключи на записи.

**0–10 секунд.** «Tracy — контроль между AI-агентом и чувствительным действием. Агент сообщает, что хочет сделать; доступ к системе хранится у Tracy». Показать Control center, агента tracy_control_demo.

**10–25 секунд.** Human approvals → database.insert. Показать intent, задачу, whitelist/лимит и policy. «Запись ждёт владельца. Подтверждается конкретное действие, а не бессрочный доступ». Нажать Approve.

**25–40 секунд.** Дождаться VERIFIED и нажать Verify evidence now. «Tracy сделала запись, отдельно прочитала БД и сверила результат с запросом». Показать receipt и подпись.

**40–50 секунд.** Вернуться к истории: запрещённый SQL имеет REJECTED, API-вызов — VERIFIED. «Для обычного разрешённого действия approval можно отключить, а недопустимое не исполняется».

**50–60 секунд.** Integrations. «Подключение через SDK, API, MCP и инструменты LangChain. Агенту даём только ключ намерений. Сегодня БД настоящая локальная, GitHub и платный API — явно помеченные симуляторы».

Если статус UNCERTAIN: показать его как честный результат неизвестного исхода; не пересоздавать операцию. Проверить localhost:8011 и data/control-provider.err.log. Если задача истекла, создать новый сценарий до записи демо. Если approval уже обработан, -NewScenario создаёт новые примеры, сохраняя старые доказательства.
