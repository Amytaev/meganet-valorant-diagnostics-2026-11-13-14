"""Build the engineer-facing package from reviewed addresses and completed native jobs."""
import argparse
import hashlib
import json
import re
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def table(headers, rows):
    return '\n'.join(['| '+' | '.join(headers)+' |', '|'+'|'.join(['---']*len(headers))+'|'] +
                     ['| '+' | '.join(str(v).replace('|','/') for v in row)+' |' for row in rows])


def parse_ping(text):
    summary = re.search(r'(?:Packets|Пакетов)\s*:[^\r\n=]*=\s*(\d+)[^\r\n=]*=\s*(\d+)[^\r\n=]*=\s*(\d+)', text, re.I)
    result = dict(parsed=bool(summary), echo_reply_lines=len(re.findall(r'\bTTL\s*=\s*\d+', text, re.I)))
    if summary:
        sent,received,lost = map(int, summary.groups())
        result.update(native_sent=sent,native_received=received,native_lost=lost,
                      native_nonresponse_pct=100*lost/sent if sent else None)
    latency = re.search(r'(?:Minimum|Минимальное)\s*=\s*(\d+).*?(?:Maximum|Максимальное)\s*=\s*(\d+).*?(?:Average|Среднее)\s*=\s*(\d+)', text,re.I|re.S)
    if latency:
        result['native_rtt_min_max_avg_ms'] = list(map(int,latency.groups()))
    result['interpretation'] = 'Native ICMP statistics only; unreachable responses and missing echo replies are not game UDP loss.'
    return result


def parse_trace(text, target):
    hops=[]
    for line in text.splitlines():
        match=re.match(r'^\s*(\d+)\s+(.+)$',line)
        if not match:
            continue
        addresses=re.findall(r'(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])',match[2])
        hops.append(dict(ttl=int(match[1]),addresses=addresses,
                         native_rtt_tokens=re.findall(r'<?\s*\d+\s*(?:ms|мс)',match[2],re.I),
                         asterisks=match[2].count('*')))
    responding=[h for h in hops if h['addresses']]
    return dict(hops=hops,destination_address_printed=any(target in h['addresses'] for h in hops),
                last_responding_hop=responding[-1] if responding else None,
                interpretation='Asterisks are missing ICMP replies, not proof of forwarded UDP loss. Trace does not expose private Riot/SDR server path.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package',type=Path)
    args=parser.parse_args(); p=args.package
    inventory=read(p/'valorant-address-inventory.json'); targets=read(p/'targets.json')
    relays=read(p/'cs2-relay-candidates.json'); batch=read(p/'measurements/batch.json')
    route_snapshot=read(p/'sources/selected-routes.json')
    assert batch['complete'] and len(batch['jobs'])==8
    results={}
    for job in batch['jobs']:
        expected=['ping.exe','-n','100',job['ip']] if job['kind']=='ping' else ['tracert.exe','-d','-h','32',job['ip']]
        assert job['argv']==expected and job['complete'] and not job['watchdog_terminated']
        raw=p/'measurements'/job['raw_file']
        assert hashlib.sha256(raw.read_bytes()).hexdigest()==job['raw_sha256']
        text=(p/'measurements'/(job['ip']+'-'+job['kind']+'.utf8.txt')).read_text(encoding='utf-8')
        parsed=parse_ping(text) if job['kind']=='ping' else parse_trace(text,job['ip'])
        results.setdefault(job['ip'],{})[job['kind']]=dict(job,parsed=parsed)
        if job['kind']=='ping':
            assert parsed['parsed'] and parsed['native_sent']==100
        else:
            assert parsed['hops'] and (parsed['destination_address_printed'] or parsed['hops'][-1]['ttl']==32)
    (p/'measurement-summary.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    lines=[
        '# Технический пакет Meganet: Valorant и CS2 / Stockholm', '',
        '**Подготовлено для проверки сетевыми инженерами; обращение не отправлено.** Нет доказанного фиксированного «IP физического игрового сервера Stockholm». Для Valorant подтверждена связь двух адресов с игровыми записями; для CS2 доступны опубликованные Valve SDR-ретрансляторы, но выбранный клиентом relay не установлен.', '',
        '## 1. Методика и время', '',
        'Методика из Word-инструкции Meganet передана владельцем текстом; сам Word не исследовался. Выполнены точные команды `ping -n 100 <IP>` и `tracert -d -h 32 <IP>`. 100 запросов — явное уточнение владельца. Не добавлялся -w: штатный timeout 4000 мс; payload ping 32 байта. Tracert не запрашивает DNS-имена. Значения параметров описаны в [ping Microsoft](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/ping) и [tracert Microsoft](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/tracert).', '',
        f"Пакетный замер: UTC {batch['start_utc']} — {batch['end_utc']}. Время +05:00 приведено для каждой команды ниже. Это отдельный ICMP-замер после исторического дневного матча, **не синхронное воспроизведение** игрового пика. Выполнялись максимум две низкоприоритетные скрытые команды одновременно, обычным пользовательским токеном на локальной Windows. Игры не запускались, настройки и античит не менялись; постоянный монитор не перезапускался.", '',
        'Для каждого запуска сохранены `.raw.txt` (точные байты stdout/stderr), `.utf8.txt` (копия для чтения) и `.json` (argv, UTC/+05 start/end, exit code, кодировка, SHA-256). Полная таблица промежуточных узлов остаётся в выводе tracert; сводка не заменяет исходник.', '',
        f"Снимок выбора маршрутов Windows: {route_snapshot['observed_local']}. Для четырёх адресов — Wi-Fi, источник CLIENT_LAN_IP_01, next hop 192.168.123.1, route/interface metric 0/30. Это один read-only снимок во время пакетного замера, не проверка каждой секунды или обратного пути; исходные поля — [selected-routes.json](sources/selected-routes.json).", '',
        '## 2. Что подтверждено и что остаётся кандидатом', '',
        '* **Подтверждено приложением:** `185.40.64.1` и `162.249.72.1` встречаются в штатных LogTravelManager + LogMapLoadModel. Для `162.249.72.1:7004` и исторического `185.40.64.1:7329` есть также GameNetDriver/RemoteAddr в LogNet. Это уровни доказательств связи с игровым подключением, а не физического размещения или независимой проверки текущего UDP peer. Travel/map-load сами по себе не доказывают успешный handshake каждой попытки.',
        '* **Кандидаты CS2:** актуальные опубликованные relay IP групп sto/sto2. Существование и PoP-метка подтверждаются конфигурацией Valve; использование данным клиентом не подтверждено. Физические CS2-серверы за SDR не определены.',
        '* **Исключено:** `104.16.56.40:443` встречается в LogHttp; это не свидетельство игрового потока. Домашний шлюз, Cloudflare и контрольные RETN тоже не выдаются за игровые серверы.', '',
        '### Зарегистрированные Valorant IP:порт', '',
        'Дубликаты из нескольких выгрузок объединены по endpoint + raw log time + категории. Часы логов независимо не верифицированы; таблица сохраняет исходный формат и не назначает ему UTC. Для :7004 днём и наблюдаемого :7039 Stockholm выбран со слов игрока; для прочих исторических портов регион неизвестен. Ping/tracert работают по IP, поэтому одна проверка каждого IP покрывает строку назначения всех его портов, но **не проверяет UDP-порт**.', '',
        table(['IP:порт','Первое / последнее время в исходном логе','Уникальных записей','Сила свидетельства'],
              [[e['endpoint'],e['first_log_time']+' / '+e['last_log_time'],e['unique_events'],
                'GameNetDriver RemoteAddr + travel/map-load' if 'RemoteAddr also' in e['evidence_strength'] else 'Travel + map-load; успешный UDP сеанс не доказан'] for e in inventory['endpoints']]), '',
        'Источники и ссылки на категории/строки: [инвентаризация](valorant-address-inventory.json), [ограниченное извлечение контекста](sources/valorant-context-allowlist.json). Полные игровые журналы, query strings, tickets, имена игроков и авторизация в пакет не включены.', '',
        '## 3. Игровой контекст и ограничения Anycast', '',
        'В дневном рейтинговом матче 14 ноября игрок сообщил повторные переходы **95→120→180→120 мс**, позже **300–400 мс примерно пять минут**. Плотные F8/F9 около 14:19–14:22; новые F8 с 14:27:50; сообщение 300–400 внесено в 14:29:10 (+05). Это не точные секунды числовых переходов. В окне 14:29:10–14:29:58 по 24 контроля на цель: медианы шлюз/near/CF/RETN-1/RETN-2 **2/3/24/93/92 мс**; максимумы 3/5/25/95/93. Игровая задержка существенно расходилась с этими контролями, которые не измеряли игровой endpoint.', '',
        'До самостоятельного перезахода в логе `185.40.64.1:7004`; после — `162.249.72.1:7004`. После перезахода сообщено ~100, затем 100–110 мс; поздние F8 — 120–130. Это временное совпадение со сменой подключения, а не доказанная причинность. Отдельно в 14:35 был краткий локальный всплеск до шлюза 118 мс; он не объясняет весь пятиминутный эпизод. Количественные игровые потери днём не сообщены.', '',
        'После конечного пакета команд владелец сообщил о новом матче: обычные 96–105 мс и подъём 100→110. Свежие LogTravelManager/LogMapLoadModel содержат **185.40.64.1:7158**; выбранный регион этого нового матча независимо не подтверждён. Нажатая до возобновления сборщика F8 не записалась: прошлый монитор был штатно остановлен в 14:49. Новый непрерывный сбор запущен в 16:32:40 только после сообщения; прошлый момент нажатия не восстановлен. Нативные проверки IP 185.40.64.1 в этом пакете предшествуют новому матчу и не измеряют его конкретный порт/поток. При трактовке raw log time как UTC новый переход/загрузка карты соответствуют примерно 16:29:32–16:29:47 (+05) и могут пересекаться с окончанием последнего CS2 ping; независимая проверка часов игры отсутствует. Проверки Riot-IP закончились раньше. Подробности: [контекст нового матча](sources/new-match-context.json). После сообщения пользователя новые длинные трассировки не запускались.', '',
        'Riot описывает Anycast-входы, внутреннюю доставку и NAT к приватным игровым серверам; точка входа не обязана совпадать с площадкой матча. Поэтому смена публичного адреса, GeoIP и окончание ICMP-трассы не доказывают смену физического сервера Stockholm. Применимость общей архитектуры не является независимым доказательством конкретного BGP-анонса этих IP в данный момент. [Riot Direct](https://www.riotgames.com/en/news/leveling-networking-multi-game-future).', '',
        '## 4. Результаты по четырём выбранным IP', '',
    ]
    compact=[]
    for target in targets['measurement_targets']:
        r=results[target['ip']]; ps=r['ping']['parsed']; ts=r['tracert']['parsed']
        native=ps.get('native_rtt_min_max_avg_ms')
        latency=f'{native[0]} / {native[2]} / {native[1]}' if native else 'нет echo RTT'
        last=ts['last_responding_hop']
        last_text=f"TTL {last['ttl']}: {', '.join(last['addresses'])}" if last else 'нет отвечающих hops'
        compact.append([target['ip'],target['game'],f"{ps['echo_reply_lines']}/100",latency,last_text])
    lines += [table(['IP','Игра / роль в разделе 2','Строк echo reply','ICMP min / avg / max, мс','Последний отвечающий hop'],compact), '',
              'Нулевое число echo reply означает отсутствие ICMP-ответов, а не измеренные 100% потерь игровых пакетов. Эти четыре адреса не являются перечнем физических серверов Stockholm.', '']
    for target in targets['measurement_targets']:
        ip=target['ip']; r=results[ip]; ping=r['ping']; trace=r['tracert']; ps=ping['parsed']; ts=trace['parsed']
        last=ts['last_responding_hop']
        last_text=f"TTL {last['ttl']}: {', '.join(last['addresses'])}; RTT проб: {', '.join(last['native_rtt_tokens'])}" if last else 'нет отвечающих узлов'
        lines += [f"### {ip} — {target['game']}", '',
                  f"Роль: {target['role']}. Регион: {target['region']}. Исторический игровой RTT: {target['historical_game_rtt_ms'] or 'не измерен / нет CS2-сеанса'}. Во время текущего ICMP-замера игровой RTT неизвестен.", '',
                  table(['Команда','Начало +05','Конец +05','Exit code','Полный вывод'],
                        [[' '.join(j['argv']),j['start_local'],j['end_local'],j['exit_code'],f"[{j['kind']} UTF-8](measurements/{ip}-{j['kind']}.utf8.txt)"] for j in [ping,trace]]), '',
                  f"Статистика ping: {ps.get('native_sent','не разобрано')} отправлено, {ps.get('native_received','не разобрано')} received по native summary, {ps.get('native_lost','не разобрано')} lost по native summary; строк echo reply с TTL: {ps['echo_reply_lines']}. Native min/max/avg RTT: {ps.get('native_rtt_min_max_avg_ms','нет RTT — нет подтверждённых echo replies')} мс. Процент native неответов: {ps.get('native_nonresponse_pct','не разобрано')}%.", '',
                  f"Tracert: адрес назначения {'присутствует' if ts['destination_address_printed'] else 'не показан как ответивший hop'}; последний отвечавший узел: {last_text}. Полные RTT всех проб и звёздочки сохранены в исходном выводе.", '',
                  '**Ограничение:** отсутствие ICMP echo reply — ограничение этой проверки; это не доказанные потери игрового UDP. Звёздочки tracert не локализуют дроп пересылаемых данных. Даже достигнутый relay/Anycast IP не раскрывает весь внутренний путь до игрового сервера.', '',
                  f"[Точные байты ping](measurements/{ip}-ping.raw.txt), [трассы](measurements/{ip}-tracert.raw.txt), [метаданные ping](measurements/{ip}-ping.json), [метаданные трассы](measurements/{ip}-tracert.json).", '']
    lines += [
        '### Сравнение видимой части двух Riot-направлений', '',
        'В этих последовательных внеигровых трассировках общий ближний участок — 192.168.123.1 → 10.0.0.229 → 89.38.164.205. К 185.40.64.1 видны 89.38.167.209 → 87.245.238.34 → 87.245.233.166 (TTL 9, около 70–71 мс). К 162.249.72.1 видны 85.29.131.24, затем 87.245.238.34 → 87.245.234.191 (TTL 9, около 74–75 мс), с неотвечающими TTL между ними. Это реальное различие видимых отвечающих интерфейсов для двух направлений **в момент нового замера**.', '',
        'В ранее сохранённых материалах PTR-метки связывали .233.166 со sto.se.retn.net, .234.191 — с waw.pl.retn.net; новый tracert -d имена не запрашивал. Ни PTR, ни последний ответивший интерфейс не доказывают географию игрового сервера. Эти поздние ICMP-трассы не восстанавливают точный маршрут в 14:29 или 14:32 и не доказывают, что именно различие транзита вызвало восстановление. Просим оператора проверить соответствующие forward/reverse игровые направления по своим данным.', '',
        '## 5. CS2: доступные диагностические узлы', '',
        'В двух настроенных библиотеках Steam не найден appmanifest_730 и существующий игровой console/network log. Это не доказательство отсутствия CS2 во всех возможных каталогах. Steam connection_log не подменяется игровым relay-логом. Новой игровой сессии не было, выбранный клиентом relay и игровой RTT CS2 неизвестны.', '',
        'Valve SDR скрывает физические адреса серверов; FakeIP/SteamID не следует отправлять в обычный ping как публичный IP. ICMP к опубликованному relay измеряет только доступ к этому узлу. [Steam SDR](https://partner.steamgames.com/doc/features/multiplayer/steamdatagramrelay).', '',
        'Valve различает прямую задержку до PoP и лучший маршрут к data center через relay. Документация SDK описывает GetDirectPingToPOP / GetPingToDataCenter; это не заявляется как проверенная команда консоли CS2 и SDK не внедрялся в игру. [SteamNetworkingUtils](https://partner.steamgames.com/doc/api/ISteamNetworkingUtils).', '',
        f"[Публичная конфигурация Valve appid 730](https://api.steampowered.com/ISteamApps/GetSDRConfig/v1/?appid=730), revision {relays['revision']}; снимок и время загрузки — в sources. Для измерения выбрано по одному relay из Kista и Bromma. Остальные адреса ниже — опубликованные диагностические кандидаты, **не проверенные участники пользовательского матча**; команды подготовлены, но массовый замер всей группы не выполнялся.", '',
        table(['PoP / регион Valve','Relay IPv4','Текущий замер','Команды при необходимости'],
              [[r['pop']+' / '+r['region_label'],r['ip'],'выполнен' if r['selected_for_current_measurement'] else 'не выполнялся',
                r['ping_command']+'; '+r['tracert_command']] for r in relays['rows']]), '',
        'Для привязки к реальному матчу понадобится пользовательская CS2-сессия и штатная диагностика/лог с выбранным relay/PoP и временем, если она доступна в установленной версии. IP входного relay, серверный PoP и скрытый игровой сервер — разные сущности. Без этих данных не выбирается «тот самый физический сервер Stockholm».', '',
        '## 6. Запрос сетевым инженерам Meganet', '',
        'Просим сравнить egress/BGP/пиринги и обратные пути к двум игровым адресам Valorant в плохой и восстановившейся фазах; проверить очереди/дропы в соответствующих абонентских/NAT-сессиях и при необходимости обратиться к Riot Direct. Для CS2 проверить достижимость указанных sto/sto2 relay, сохраняя отличие этого участка от скрытого relay→game-server. Нужны данные пересылаемого трафика и корреляция времени, а не вывод о вине узла по ICMP-звёздочкам. Абонентскую идентификацию владелец добавляет вручную; пароли и игровые токены не нужны.', '',
        '## 7. Состав пакета и контроль целостности', '',
        'README.md — этот документ; measurements/ — восемь полных выводов с raw/UTF-8 копиями и метаданными; measurement-summary.json — разобранные ICMP результаты; targets.json и valorant-test-plan.json — назначения и методика; valorant-address-inventory.json — доказательства связи с логами; cs2-relay-candidates.json — полный список опубликованных Stockholm relay с командами; sources/ — обезличенные контексты и первичные источники. SHA256SUMS.txt проверяет все включённые файлы. Публичная конфигурация не содержит учётных данных; полные приватные игровые логи не приложены. Пакет подготовлен для владельца и сохранения в приватной ветке, провайдеру автоматически не отправлен.',
        '', 'Для повторного конечного замера без запуска игры: `python tools/run_meganet_probes.py --targets targets.json --output measurements-next --execute`. Без --execute инструмент только печатает план. Существующий каталог результата не перезаписывается. Повтор не нужен для прочтения этого пакета. Команды для остальных опубликованных relay подготовлены в cs2-relay-candidates.json; они не запускались автоматически.',
    ]
    (p/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf-8',newline='\n')
    for ip,r in results.items():
        print(ip, json.dumps(r['ping']['parsed'],ensure_ascii=False),'last_hop',r['tracert']['parsed']['last_responding_hop'])


if __name__=='__main__':
    main()
