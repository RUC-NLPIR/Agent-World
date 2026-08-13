import sys, requests

def smoke(svc, env):
    url = f'https://{env}.acme.io/{svc}/health'
    r = requests.get(url, timeout=5)
    if r.status_code != 200:
        print(f'FAIL {svc} {env}: {r.status_code}', file=sys.stderr)
        sys.exit(1)
    print(f'OK {svc} {env}')

if __name__ == '__main__':
    smoke(sys.argv[1], sys.argv[2])
