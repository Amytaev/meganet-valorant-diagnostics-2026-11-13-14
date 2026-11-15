"""Portable HTML report: local PNG figures embedded, no JavaScript or remote assets."""
import argparse
import base64
import hashlib
import html
import re
from pathlib import Path

REPOSITORY_BASE = 'https://github.com/Amytaev/meganet-valorant-diagnostics-2026-11-13-14/blob/main/investigation'

def inline(text,source,project):
    text=html.escape(text,quote=False)
    text=re.sub(r'`([^`]+)`',r'<code>\1</code>',text)
    text=re.sub(r'\*\*(.+?)\*\*',r'<strong>\1</strong>',text)
    def link(match):
        label,target=match.groups()
        if not target.startswith(('https://','http://')):
            resolved=(source.parent/target).resolve()
            try:
                relative=resolved.relative_to(project).as_posix()
                base=REPOSITORY_BASE.replace('/blob/','/tree/') if resolved.is_dir() else REPOSITORY_BASE
                target=f'{base}/{relative}'
            except ValueError:
                target='#'
        return '<a href="'+html.escape(target,quote=True)+'">'+label+'</a>'
    return re.sub(r'\[([^\]]+)\]\(([^)]+)\)',link,text)


def render(source):
    source=source.resolve(); project=source.parents[1]
    lines=source.read_text(encoding='utf-8').splitlines(); output=[]; index=0; listing=None
    def end_list():
        nonlocal listing
        if listing:
            output.append('</'+listing+'>'); listing=None
    while index<len(lines):
        line=lines[index]; index+=1
        if not line.strip():
            end_list(); continue
        if line.startswith('```'):
            end_list(); code=[]
            while index<len(lines) and not lines[index].startswith('```'):
                code.append(lines[index]); index+=1
            index+=1; output.append('<pre><code>'+html.escape('\n'.join(code))+'</code></pre>'); continue
        if line.startswith('|'):
            end_list(); rows=[line]
            while index<len(lines) and lines[index].startswith('|'):
                rows.append(lines[index]); index+=1
            output.append('<div class="table"><table><thead><tr>')
            output.extend('<th>'+inline(c.strip(),source,project)+'</th>' for c in rows[0].strip('|').split('|'))
            output.append('</tr></thead><tbody>')
            for row in rows[2:]:
                output.append('<tr>'+''.join('<td>'+inline(c.strip(),source,project)+'</td>' for c in row.strip('|').split('|'))+'</tr>')
            output.append('</tbody></table></div>'); continue
        image=re.fullmatch(r'!\[(.*?)\]\((.*?)\)',line)
        if image:
            end_list(); title,path=image.groups(); path=(source.parent/path).resolve(); path.relative_to(source.parent)
            encoded=base64.b64encode(path.read_bytes()).decode('ascii')
            output.append('<figure><img alt="'+html.escape(title,quote=True)+'" src="data:image/png;base64,'+encoded+'"><figcaption>'+html.escape(title)+'</figcaption></figure>'); continue
        heading=re.match(r'^(#{1,6}) (.+)',line)
        if heading:
            end_list(); level=len(heading[1]); output.append(f'<h{level}>'+inline(heading[2],source,project)+f'</h{level}>'); continue
        item=re.match(r'^(?:([-*])|(\d+)\.) (.+)',line)
        if item:
            kind='ol' if item[2] else 'ul'
            if listing!=kind:
                end_list(); output.append('<'+kind+'>'); listing=kind
            output.append('<li>'+inline(item[3],source,project)+'</li>'); continue
        end_list(); output.append('<p>'+inline(line,source,project)+'</p>')
    end_list()
    style='''body{font:16px/1.6 "Segoe UI",Arial,sans-serif;color:#20314a;background:#f1f5f9;margin:0}main{max-width:1140px;margin:28px auto;padding:38px 46px;background:white;border-top:6px solid #1768ac}h1{font-size:30px;line-height:1.25;color:#102941}h2{font-size:23px;margin-top:38px;border-bottom:1px solid #dbe4ed;padding-bottom:7px}p{margin:15px 0}a{color:#1768ac}code{font:14px Consolas,monospace;background:#edf2f7;padding:2px 5px;border-radius:3px}pre{background:#edf2f7;padding:18px;white-space:pre-wrap}.table{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}th,td{border:1px solid #dbe4ed;padding:9px 10px;text-align:left;vertical-align:top}th{background:#e8f1fa}tr:nth-child(even){background:#f8fafc}figure{margin:25px 0}figure img{width:100%;height:auto;border:1px solid #e4e9ef}figcaption{color:#58677a;font-size:13px}li{margin-bottom:9px}footer{font-size:12px;color:#68778a;margin-top:36px;word-break:break-all}@media(max-width:700px){main{padding:20px;margin:0}h1{font-size:25px}}@media print{body{background:white}main{margin:0;padding:0;border:0}figure,table{break-inside:avoid}a{color:inherit}h2{break-after:avoid}}'''
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    title=html.escape(next((line[2:] for line in lines if line.startswith('# ')),source.stem))
    image_count=len(re.findall(r'<figure>', ''.join(output)))
    return '<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+title+'</title><style>'+style+'</style></head><body><main>'+''.join(output)+'<footer>SHA-256 Markdown: '+digest+'. Встроено графиков: '+str(image_count)+'. Внешних ресурсов и скриптов нет.</footer></main></body></html>'


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('source',type=Path); parser.add_argument('output',type=Path)
    parser.add_argument('--repository-base',default=REPOSITORY_BASE,help='GitHub blob URL for the project root; used for relative document links')
    args=parser.parse_args(); REPOSITORY_BASE=args.repository_base.rstrip('/'); args.output.write_text(render(args.source),encoding='utf-8'); print(args.output)
