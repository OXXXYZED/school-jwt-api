# School API — JWT-аутентификация для учителей и учеников

REST API на Django + Django REST Framework. Пользователи (учителя и ученики) логинятся,
передавая логин и пароль в Base64 (`Authorization: Basic …`), получают пару JWT-токенов
(access + refresh) и дальше передают access-токен с каждым запросом (`Authorization: Bearer …`).

Демо-стенд: https://proweb.inzavic.uz/ (Swagger UI с инструкцией) · Postman-коллекция: `postman/`.

Стек: Python 3.11+, Django 5.2 LTS, DRF, [SimpleJWT](https://django-rest-framework-simplejwt.readthedocs.io/),
drf-spectacular (Swagger), SQLite; для деплоя — Docker Compose, gunicorn, Caddy (автоматический HTTPS).

## Структура проекта

```
.
├── config/             # конфигурация Django-проекта
│   ├── settings.py     #   основные настройки (env-переменные, DRF, JWT, throttling)
│   ├── urls.py         #   корневые маршруты (`/` → Swagger UI)
│   └── swagger_*       #   инструкция на странице docs и автоподстановка токена
├── users/              # приложение для управления пользователями
│   ├── models.py       #   User с ролью teacher/student
│   ├── basic_auth.py   #   разбор `Authorization: Basic base64(username:password)`
│   ├── tokens.py       #   выпуск JWT-пары с claim'ами role/username
│   ├── permissions.py  #   IsTeacher
│   ├── views.py        #   login / register / me / students
│   └── urls.py
├── app/                # приложение школы: оценки с ролевым доступом
│   ├── models.py       #   Grade
│   ├── permissions.py  #   учитель пишет, автор оценки редактирует
│   ├── views.py        #   GradeViewSet
│   └── management/commands/seed_demo.py
├── deploy/            # серверные скрипты деплоя (host-caddy / compose), diagnose, Caddyfile
├── postman/           # Postman-коллекция: сценарий по ролям с автотестами
├── Dockerfile
├── docker-compose.yml
└── manage.py
```

`settings.py` и `urls.py` лежат в пакете проекта `config/` — стандартная раскладка Django:
так `app/` и `users/` остаются обычными приложениями.

## Запуск

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # DJANGO_DEBUG=1 для локальной разработки
python manage.py migrate
python manage.py seed_demo      # teacher / student1 / student2, пароль school-demo-pass
python manage.py runserver
```

- Swagger UI: http://127.0.0.1:8000/ (редирект на `/api/docs/`). Инструкция — в шапке страницы:
  **Authorize → basicAuth**, затем **POST /api/auth/login/ → Execute**; access-токен из ответа
  сам подставляется в **jwtAuth** (и после `/api/auth/refresh/` тоже)
- Админка: http://127.0.0.1:8000/admin/ (`python manage.py createsuperuser`)

Тесты и линтер:

```bash
python manage.py test
ruff check . && ruff format --check .
```

## Postman

`postman/school-api.postman_collection.json` — сценарий по ролям: учитель (логин, ученики,
выставление и правка оценки) → ученик (видит только свои оценки, на запись — `403`) → токены
(refresh с ротацией, повторное использование старого refresh — `401`, verify, logout) → уборка
(созданная оценка удаляется) → ошибки и регистрация. Токены и id сохраняются в переменных
коллекции автоматически, каждый запрос проверяется тестами (34 проверки).

1. Import → файл коллекции.
2. В переменных коллекции задать `password` (пароль демо-пользователей); `baseUrl` по умолчанию —
   демо-стенд, для локального запуска — `http://127.0.0.1:8000`.
3. Run collection.

Логин учителя показывает Base64 вручную (pre-request скрипт кодирует `username:password`), логин
ученика — через вкладку Basic Auth. Из консоли:

```bash
npx newman run postman/school-api.postman_collection.json \
  --env-var baseUrl=http://127.0.0.1:8000 --env-var password=school-demo-pass
```

Логин ограничен 10 попытками в минуту с IP (за прогон — 4), а каждый прогон регистрирует нового
ученика `postman_<timestamp>`.

## Деплой на VPS

Нужен домен, A-запись которого указывает на VPS. Если домена нет, подойдёт `<IP-адрес>.sslip.io`
(например, `203.0.113.10.sslip.io`): такое имя резолвится в IP, и Let's Encrypt выдаёт для него
сертификат. HTTPS-сертификат получает и продлевает Caddy; `DEBUG` выключен, миграции применяются
при каждом деплое.

Два варианта (`deploy/remote-deploy.sh` выбирает сам, если не задан `DEPLOY_TARGET`):

| | `host-caddy` | `compose` |
|---|---|---|
| Когда | на сервере уже работает Caddy (systemd) с другими сайтами | 80/443 свободны |
| Приложение | venv + systemd-сервис `school-api` (не root) на `127.0.0.1:8800` | Docker Compose |
| Прокси | файл `/etc/caddy/<домен>.caddy` + строка `import` в Caddyfile; `caddy validate`, мягкий reload, при ошибке старый конфиг восстанавливается | свой Caddy в контейнере |
| Данные | `/var/lib/school-api/db.sqlite3` | volume `db` |
| Админ-команды | `/opt/school-api/manage createsuperuser` | `docker compose exec web python manage.py …` |
| Логи | `journalctl -u school-api` | `docker compose logs web` |

Оба варианта ничего не меняют, если порт уже занят чужим процессом: деплой останавливается с
объяснением до первых изменений.

### Автоматически: GitHub Actions (`.github/workflows/deploy.yml`)

Workflow заходит на сервер по SSH, загружает код и запускает `deploy/remote-deploy.sh`. Первый
запуск всё подготавливает (секретный ключ генерируется на сервере и там же хранится), следующие
обновляют код, сохраняя конфигурацию и данные. В конце workflow проверяет
`https://<домен>/api/docs/` снаружи. Деплой запускается при каждом push в `main` и вручную
(Actions → Deploy → Run workflow); режим `diagnose` только показывает состояние сервера и домена.

1. Ключ только для деплоя, на своей машине:
   `ssh-keygen -t ed25519 -f ~/.ssh/school-deploy -N "" -C github-actions-deploy`
   (в Windows PowerShell: `ssh-keygen -t ed25519 -f "$env:USERPROFILE\.ssh\school-deploy" -C github-actions-deploy`
   и дважды Enter на вопрос о passphrase — PowerShell не передаёт пустой аргумент `-N ""`)
2. На VPS добавить `~/.ssh/school-deploy.pub` в `~/.ssh/authorized_keys` пользователя, от которого
   идёт деплой: root (для `host-caddy` обязательно) или пользователь из группы `docker` (`compose`). Если пользователь создан через
   `useradd` без пароля, sshd может считать его заблокированным — тогда `sudo usermod -p '*' <user>`.
3. В GitHub: Settings → Secrets and variables → Actions.
   - Variables: `DEPLOY_HOST` (IP или хост), `DOMAIN`; при необходимости `DEPLOY_USER`
     (по умолчанию `root`), `DEPLOY_PORT` (по умолчанию `22`), `DEPLOY_TARGET`
     (`auto` / `host-caddy` / `compose`) и `DEPLOY_APP_PORT` (по умолчанию `8800`).
   - Secrets: `DEPLOY_SSH_KEY` (содержимое приватного `~/.ssh/school-deploy`) и `DEMO_PASSWORD`
     (пароль демо-пользователей `teacher`, `student1`, `student2`; создаются один раз).

Пока `DEPLOY_HOST` и `DOMAIN` не заданы, job деплоя пропускается.

### Вручную (вариант compose)

```bash
git clone https://github.com/OXXXYZED/school-jwt-api.git && cd school-jwt-api
cp .env.example .env
# в .env: DOMAIN=<домен> и DJANGO_SECRET_KEY=<вывод команды ниже>
python3 -c "import secrets; print(secrets.token_urlsafe(50))"

docker compose up -d --build
docker compose exec web python manage.py seed_demo --password '<пароль для проверяющих>'
docker compose exec web python manage.py createsuperuser   # по желанию, для /admin/
```

Обновление: `git pull && docker compose up -d --build`.

## API

| Метод | URL | Доступ | Описание |
|---|---|---|---|
| POST | `/api/auth/register/` | все | Регистрация (всегда создаёт ученика) |
| POST | `/api/auth/login/` | все | `Authorization: Basic base64(username:password)` → `{access, refresh, user}` |
| POST | `/api/auth/refresh/` | все | `{refresh}` → новая пара (старый refresh отзывается) |
| POST | `/api/auth/verify/` | все | `{token}` → 200, если токен валиден |
| POST | `/api/auth/logout/` | все | `{refresh}` → refresh-токен в blacklist |
| GET, PATCH | `/api/users/me/` | авторизованные | Профиль; `role` и `username` только для чтения |
| GET | `/api/users/students/` | учитель | Список активных учеников, `?search=` |
| GET | `/api/school/grades/` | авторизованные | Учитель — все оценки, ученик — только свои; `?student=`, `?subject=` |
| POST | `/api/school/grades/` | учитель | Поставить оценку (1–5); автор = текущий учитель |
| GET | `/api/school/grades/{id}/` | авторизованные | Ученик видит только свою (чужая → 404) |
| PATCH, PUT, DELETE | `/api/school/grades/{id}/` | учитель-автор | Чужую оценку изменить нельзя (403) |

### Пример сессии

```bash
# 1. Логин: username:password кодируется в Base64 и передаётся в заголовке
CREDS=$(printf '%s' 'teacher:school-demo-pass' | base64)      # dGVhY2hlcjpzY2hvb2wtZGVtby1wYXNz
curl -X POST http://127.0.0.1:8000/api/auth/login/ -H "Authorization: Basic $CREDS"
# то же самое короче: curl -u teacher:school-demo-pass -X POST .../api/auth/login/

# 2. Запросы с access-токеном
curl http://127.0.0.1:8000/api/school/grades/ -H "Authorization: Bearer <access>"

# 3. Обновление пары по refresh-токену
curl -X POST http://127.0.0.1:8000/api/auth/refresh/ -H "Content-Type: application/json" \
     -d '{"refresh": "<refresh>"}'
```

Ответ логина:

```json
{
  "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0b2tlbl90eXBlIjoiYWNjZXNzIiwi...",
  "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0b2tlbl90eXBlIjoicmVmcmVzaCIs...",
  "user": {"id": 1, "username": "teacher", "role": "teacher", "first_name": "Anna", "...": "..."}
}
```

Payload access-токена (вторая часть JWT, Base64url):
`{"token_type": "access", "exp": …, "iat": …, "jti": "…", "user_id": "1", "username": "teacher", "role": "teacher"}`.

### Коды ответов логина

| Ситуация | Код |
|---|---|
| Успех | 200 |
| Нет заголовка / не `Basic` | 401 + `WWW-Authenticate: Basic` |
| Невалидный Base64, нет `:` | 400 |
| Неверный логин/пароль, неактивный пользователь | 401, одинаковое сообщение (без user enumeration) |
| Превышен лимит попыток (10/мин с IP) | 429 |

## Решения и компромиссы

- **Base64 — это кодирование, а не шифрование.** Логин по `Basic` и JWT безопасны только поверх HTTPS.
  Payload JWT тоже просто Base64url — в claim'ы не кладётся ничего секретного.
- **Base64-креды разбираются во view, а не в DRF authentication class.** DRF выполняет аутентификацию
  *до* throttling, поэтому неудачные попытки через authentication class не попадали бы под rate limit
  и перебор паролей не ограничивался бы. Декодирование строгое (`validate=True`, UTF-8 по RFC 7617):
  мусорные символы не отбрасываются молча, кириллические пароли работают, пароль может содержать `:`.
- **Права проверяются по пользователю из БД, а не по claim'у `role`.** `JWTAuthentication` загружает
  пользователя на каждый запрос, поэтому смена роли или деактивация действуют сразу, без перелогина.
  `role` в токене — подсказка для клиента (например, для роутинга UI).
- **Короткий access (15 мин) + ротация refresh (7 дней) с blacklist.** Повторное использование старого
  refresh отклоняется. `logout` отзывает refresh-токен; уже выданный access живёт до истечения срока —
  это стандартный компромисс stateless JWT.
- **Учителя не регистрируются сами.** Открытая регистрация с выбором роли позволила бы любому стать
  учителем, поэтому `/register/` всегда создаёт ученика, а учителей заводит администратор
  (админка, поле `role`) или `seed_demo` для локальной разработки.
- **Учитель видит все оценки, но меняет только свои.** Ученик видит только свои; чужая оценка для
  ученика — 404 (не раскрываем факт существования).

- **IP клиента для rate limit берётся из `REMOTE_ADDR`.** `X-Forwarded-For` учитывается только при
  `DJANGO_NUM_PROXIES>0` (в compose — 1, это Caddy). Иначе DRF использует заголовок как есть, и
  перебор паролей обходит лимит подменой заголовка в каждом запросе (на это есть регрессионный тест).

## Что добавить для продакшена

- PostgreSQL вместо SQLite.
- Общий кэш (Redis) для throttling. Сейчас это LocMemCache, поэтому gunicorn запущен одним процессом
  с потоками: так счётчики общие. Для нескольких воркеров или серверов нужен Redis.
- HSTS, CORS для фронтенда, смена и сброс пароля.
