import urllib.request, json

queries = ['002431', '590', '000000002431', 'jpg']
for q in queries:
    url = f'http://127.0.0.1:8000/api/files/search?workspace_id=1&query={q}&limit=5'
    try:
        data = json.loads(urllib.request.urlopen(url).read())
        print(f'Search "{q}": {len(data["files"])} results')
        for f in data['files'][:3]:
            print(f'  id={f["id"]}, filename={f["filename"]}')
    except Exception as e:
        print(f'Error for "{q}": {e}')
