# ITMC OJ production trên Ubuntu

Production dùng uWSGI, MariaDB, Redis AOF, Celery worker, đúng một Beat,
bridge, WebSocket và Nginx. Judge worker là hệ thống ngoài repository.
Không cần sửa `dmoj/repo` để cấu hình deployment. Không chạy `runserver`.

## Chuẩn bị VPS

Dùng Ubuntu 24.04 LTS, CPU/RAM và dung lượng phù hợp số submission. Cài Git,
GNU Make, Bash, OpenSSL, Python 3 và Docker Engine với Compose plugin **>= 2.24.4**
(cần hỗ trợ `!override`). Theo hướng dẫn Docker chính thức:
https://docs.docker.com/engine/install/ubuntu/ . Trên VPS Ubuntu 24.04 mới:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg
sudo chmod 644 /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu noble stable" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update
sudo apt-get install git make openssl python3 docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
docker compose version
docker info
git clone --recurse-submodules https://github.com/ITMC-Projects/ITMC-OJ-docker.git
cd ITMC-OJ-docker
git submodule update --init --recursive
make prod-init
```

Tài khoản triển khai cần quyền Docker (quyền tương đương root). Chỉ mở SSH,
80 và 443 ở firewall/cloud security group. Không mở 3306, 6379, 9998,
15100–15102. Không dựa riêng vào UFW để chặn published Docker ports;
kiểm tra cả firewall nhà cung cấp/DOCKER-USER. Không dùng production cho mã không tin cậy;
chạy judge trên máy riêng.

## Cấu hình và triển khai lần đầu

`make prod-init` tạo các file còn thiếu, directory dữ liệu và secrets ngẫu nhiên
bằng OpenSSL, mode 600. Chạy lại giữ nguyên mọi secret không rỗng, kể cả placeholder
đã nhập; validation sẽ báo lỗi placeholder để người quản trị sửa chủ động.
Không đưa env, backup hoặc dữ liệu thật lên Git. Sao lưu secrets riêng trong kho bảo mật.

Sửa các file `dmoj/production/env/*.env` từ template đã tạo:

* `site.env`: DNS trong HOST/ALLOWED_HOSTS, HTTPS SITE_FULL_URL/MEDIA_URL,
  CSRF_TRUSTED_ORIGINS; endpoint OTS HTTPS và token dịch vụ.
* `mysql.env`: database/user/password riêng. `mysql-admin.env`: root password.
  MariaDB chỉ dùng các giá trị này khi tạo database lần đầu; đổi env không tự đổi
  mật khẩu trong database đã tồn tại. Phải đổi tài khoản bằng SQL trước khi đổi env.
* `prod.env`: bind IP judge, mặc định loopback. Project name cố định `itmc-oj-prod`.

Giá trị env là literal không quote, không `$`, backtick hay nội suy shell.
`OTS_SYNC_SERVICE_TOKEN` phải trùng `OJ_SYNC_SERVICE_TOKEN` trên OTS. `prod-init`
không thay đổi OTS. Production yêu cầu HTTPS hợp lệ cho OTS, không cho internal HTTP.
OTS_SYNC_AUTO_ENABLED=1 giữ lịch sync 30 giây sẵn có; có thể đặt 0 để chỉ sync thủ công.
Đảm bảo DNS/network của OTS truy cập được từ container; không dùng localhost để chỉ host.

```bash
make prod
make prod-ps
make prod-logs SERVICE=site
```

`make prod` validate env/Compose, build base trước application images, chờ DB/Redis
healthy, migrate, build CSS/static/translations, start/recreate và chạy deployment checks.
Base là build-only profile, không chạy một container Python thừa. Source được COPY
vào image production; image dùng prefix riêng, không đổi tag image dev. Bản dịch .mo
được compile trong image, CSS/static được build vào volume assets. Dev vẫn dùng
PowerShell và source bind như cũ. Lần đầu cần tạo admin/fixtures rõ ràng, không tự seed:

```bash
docker compose -p itmc-oj-prod --env-file dmoj/production/env/prod.env -f dmoj/docker-compose.yml -f dmoj/docker-compose.prod.yml exec site python3 manage.py createsuperuser
# Chỉ khi cài mới và thực sự cần navbar/language fixtures:
docker compose -p itmc-oj-prod --env-file dmoj/production/env/prod.env -f dmoj/docker-compose.yml -f dmoj/docker-compose.prod.yml exec site python3 manage.py loaddata navbar language_small
```

## Config mapping và dữ liệu

| File trong production/config | Đích container | Service |
|---|---|---|
| django/local_settings.py | /site/dmoj/local_settings.py | site, celery, beat, bridged |
| uwsgi.ini | /site/uwsgi.ini | site |
| websocket/config.js | /app/site/websocket/config.js | wsevent |
| nginx/nginx.conf | /etc/nginx/conf.d/nginx.conf | nginx |
| nginx/default.conf | /etc/nginx/conf.d/default.conf | nginx |

Tất cả config mount read-only, file riêng, không mount đè thư mục source. File
default.conf rỗng vô hiệu hóa virtual host mặc định của image Nginx. Override dùng
`!override` thay thế toàn bộ volumes/ports/env_file/depends_on của base; không giữ
env dev, bind database dev, source dev hay port 80/9998 ngoài ý muốn. Luôn gọi qua
Make/script để giữ project name cố định; không chạy Compose base riêng cho production.

Sau khi sửa config/env, dùng `make prod-up` (hoặc prod-restart) để force recreate;
Docker bind mount file có thể còn inode cũ sau atomic-save nên restart đơn thuần
không bảo đảm áp dụng config. Khi sửa source/Dockerfile dùng `make prod`.

Database, Redis và Beat có named volumes thuộc project `itmc-oj-prod`. Assets/cache
cũng có project namespace riêng. Media/problems ở `production/data`, khác hoàn toàn
`dmoj/media`, `dmoj/problems`, `dev_database` và bind `dmoj/database`.
`prod-down` không có `-v`, không xóa dữ liệu. Không dùng `docker volume prune`
hoặc `down -v` trên production. Không đổi project name hoặc scale Beat; tên container
cố định và scale 1 bảo vệ một instance trong deployment trên host này.

## Reverse proxy HTTPS

Nginx container chỉ public `127.0.0.1:10080`. Cài Nginx/Caddy trên **cùng VPS**
để terminate TLS. Cấu hình ví dụ Nginx host sau khi đã có certificate:

```nginx
server {
    listen 80;
    server_name YOUR_DOMAIN;
    return 301 https://$host$request_uri;
}
server {
    listen 443 ssl;
    server_name YOUR_DOMAIN;
    ssl_certificate /etc/letsencrypt/live/YOUR_DOMAIN/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/YOUR_DOMAIN/privkey.pem;
    client_max_body_size 48M;
    location / {
        proxy_pass http://127.0.0.1:10080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
    }
}
```

Thay YOUR_DOMAIN, cấp chứng chỉ với ACME/Certbot, kiểm tra `nginx -t`, reload và
cấu hình renewal. Nếu dùng media hostname khác, proxy hostname đó về cùng dịch vụ.
Proxy host phải ghi đè X-Forwarded-For; không tin header do client gửi. Nginx trong
container luôn ghi đè X-Forwarded-Proto=https cho uWSGI, vì cổng loopback này là
upstream dành riêng cho TLS proxy. Không publish upstream ra Internet hoặc dùng nó
làm HTTP website công khai. Các process trên VPS và container cùng network được tin cậy.
Django bật SecurityMiddleware, HTTPS redirect, secure cookies, CSRF và HSTS cho
hostname hiện tại. HSTS includeSubDomains/preload cố ý không bật; chỉ hai warning
security.W005/W021 được miễn trong deployment check.

## External Judge và kiểm tra nghiệp vụ

Đăng ký judge trong Django Admin, tạo judge ID/key riêng và cấu hình judge worker
kết nối private VPN IP VPS:9999. Đặt JUDGE_BIND_IP về IP VPN, firewall chỉ cho IP
judge worker. Bridge TCP không có TLS công khai; dùng WireGuard hoặc SSH tunnel.
Với tunnel `ssh -N -L 9999:127.0.0.1:9999 deploy@VPS`, worker kết nối localhost:9999.
9998 chỉ giao tiếp site–bridge trong Docker, không public. Problem data cần được
đồng bộ sang worker theo cơ chế hiện có. Không thêm simulated judge ở deployment này.

```bash
make prod-check
make prod-logs SERVICE=bridged
make prod-logs SERVICE=celery
make prod-logs SERVICE=beat
curl -I https://YOUR_DOMAIN/
```

Healthchecks kiểm tra MariaDB initialized, Redis ping, uWSGI TCP, bridge TCP,
WebSocket HTTP listener, worker ping đúng node và Nginx /healthz. Beat chỉ kiểm tra
process running qua Compose; monitoring cần theo dõi lịch task thực tế. Docker
restart policy khởi động lại khi process chết; unhealthy không tự restart process.
Sau triển khai phải thử login/admin, OTS manual/auto sync (dashboard kết quả),
upload media, static, kết nối WSS `/event/`, long polling `/channels/`, gửi submission
và xác nhận judge grading. Kiểm tra dashboard monitoring và background task.
Các luồng này cần tài khoản, OTS và judge thật, không thay thế bằng healthcheck.

## Lệnh vận hành

`prod-build`: build base rồi app. `prod-up`: recreate không build. `prod-migrate`:
chờ DB/Redis rồi migrate. `prod-static`: rebuild static. `prod-check`: kiểm tra env,
Compose, Django deployment, Nginx và unapplied migrations. `prod-down`: stop/remove
container/network, giữ data. `prod-logs SERVICE=...`: follow logs, rotation 10MB × 5
cho mỗi service dài hạn. `prod-ps`: trạng thái. Không in `compose config` đầy đủ
ra log công khai vì có thể chứa secrets.

## Backup, restore và rollback

```bash
make prod-backup
make prod-restore BACKUP=/absolute/path/oj-TIMESTAMP.tar.gz
```

Backup gây maintenance: dừng nginx/site/worker/beat/bridge/WebSocket, dump SQL bằng
root qua env trong container (không truyền password trên CLI), đóng gói media/problems,
khởi động lại. File timestamp ở production/data/backups, mode private. Redis queues,
cache và Beat schedule không thuộc backup; cần drain task đang chạy trước maintenance,
đối chiếu OTS run đang xử lý sau recovery. Backup không chứa secrets hoặc source:
lưu secrets và Git commit/submodule commit/image IDs riêng, mã hóa backup khi chuyển
offsite. Đặt retention/cron phù hợp dung lượng và kiểm tra restore trên VPS staging.

Restore kiểm tra format, member names và từ chối symlink/path traversal, yêu cầu gõ
RESTORE trước ghi. SQL thay database hiện tại; media/problems cũ được giữ ở backups
với hậu tố before-timestamp. Cần đủ dung lượng. Restore để application dừng sau khi
hoàn tất, cho phép deploy đúng version trước khi mở traffic. Nếu backup/restore thất
bại sau khi dừng writers, services có thể còn dừng; kiểm tra lỗi trước `prod-up`.
SQL restore không atomic: phải có backup đã xác thực trước khi restore. Không nạp
archive không tin cậy; SQL bên trong là lệnh quản trị database.

Trước update: `make prod-backup`, ghi Git SHA của parent và `git submodule status`,
lưu image IDs bằng `docker image inspect`, fetch/checkout revision đã review và
`git submodule update --init --recursive`, rồi `make prod`. Với migration thay schema,
đặt maintenance và dừng app bằng prod-down trước deploy để không có worker phiên bản
cũ chạy trong lúc migrate. Không chạy hai lệnh deployment/backup đồng thời.

Rollback code: checkout parent SHA cũ, sync submodule rồi build lại. Nếu migration
không tương thích ngược, restore backup trước update và deploy đúng code cũ; không
chạy reverse migration khi chưa đánh giá. Static được tái tạo từ code tương ứng.
Backup source/image quan trọng vì dependency upstream chưa khóa đầy đủ có thể khiến
build lại không tạo ra image giống hệt trước đó.

## Troubleshooting và giới hạn kiểm chứng

* Placeholder/weak secret: sửa key được báo trong production/env; không dùng env dev.
* Unknown tag !override: nâng Compose >=2.24.4. Docker unavailable: kiểm tra daemon,
  Linux containers, quyền socket và `docker info`.
* DB unhealthy/access denied: xem prod-logs SERVICE=db, kiểm tra credentials đã tạo
  ban đầu; không xóa volume để xử lý lỗi đăng nhập.
* 502: kiểm tra site need-app/uWSGI, migrations, health và Nginx resolver. Mixed content,
  CSRF hoặc redirect: kiểm tra HTTPS URL, Host, trusted origins và proxy headers.
* WSS lỗi: kiểm tra Upgrade/Connection và timeout ở cả hai proxy. Judge offline:
  kiểm tra VPN bind IP/firewall, judge ID/key, bridge log và problem data phía judge.
* Permission media: init đặt public directory 755, file upload 644. Env/backups giữ
  private. Không chmod 777. Kiểm tra dung lượng Docker/backup khi ghi file lỗi.
* OTS lỗi: kiểm tra HTTPS certificate/DNS/token giống phía OTS, xem admin sync run
  và worker/beat logs; không log service token. Quy trình recover interrupted sync
  trong source chỉ thực hiện khi worker liên quan đã dừng.

Giữ Django major version theo source. Django 3.2 đã hết extended support:
https://www.djangoproject.com/weblog/2024/apr/03/bugfix-release/ . Base hiện dùng
Node 18 đã EOL: https://nodejs.org/en/about/eol . WebSocket production chọn Node 24,
cần runtime regression test. Python 3.11 + Django 3.2 và dependency ranges/git URLs
hiện tại cũng cần kiểm chứng build/compatibility; không khẳng định reproducible build.
Nâng Django/base Node và khóa dependency là công việc tiếp theo cần đánh giá nghiệp vụ.

Môi trường thực hiện thay đổi có Docker Compose CLI nhưng Docker Linux daemon không
chạy: chưa kiểm chứng image build, migrations, Django deploy checks trong container,
Nginx runtime, backup/restore với DB thật hoặc E2E OTS/judge. Kiểm tra tĩnh và
Compose merge được ghi trong `dmoj/production/VALIDATION.md`; phải chạy `make prod`
và checklist nghiệp vụ phía trên trên staging Linux trước khi mở traffic thật.
