Install with `python3 setup.py install` 

Collects dust or balances from a bunch of private keys you scraped off the internet or whatever with My Ether Wallet. 
Can scan/collect on 5,500~ wallets in a few hours. Nothing fancy 👍

Example: `ethdumper -iL bunchakeys.txt -w 6 -o outfile.json`

Usage: 

```
usage: MyEtherWallet Dumper [-h] [-v] [-iL INLIST] [-k SINGLEKEY] [-w WORKERS] [-o OUTFILE] [--http-proxy HTTP_PROXY] [--https-proxy HTTPS_PROXY] [--socks-proxy SOCKS_PROXY] [--proxy-user PROXY_UNAME] [--proxy-pass PROXY_PASS] [--to-wallet RXWALLET]
                            [--fill-gas CHEVRON]

optional arguments:
  -h, --help            show this help message and exit
  -v                    Enable verbose output. Ex: -v, -vv, -vvv
  -iL INLIST, --input-list INLIST
                        Use a list of private keys.
  -k SINGLEKEY, --key SINGLEKEY
                        Use only a single private key.
  -w WORKERS, --workers WORKERS
                        Number of selenium workers to use. Default: 12
  -o OUTFILE, --outfile OUTFILE
                        Dump results to this JSON file.

Proxy Settings:
  --http-proxy HTTP_PROXY
                        HTTP Proxy for Selenium. Ex: 127.0.0.1:8080
  --https-proxy HTTPS_PROXY
                        HTTPS Proxy for Selenium. Ex: 127.0.0.1:8080
  --socks-proxy SOCKS_PROXY
                        SOCKS Proxy for Selenium. Ex: 127.0.0.1:9050
  --proxy-user PROXY_UNAME
                        Username for proxy authentication.
  --proxy-pass PROXY_PASS
                        Password for proxy authentication.

Transfer options:
  --to-wallet RXWALLET  Dump everything in the wallet to this address.
  --fill-gas CHEVRON    If the TX wallet doesn't have the required gas, fill it first from this private key. (File pointing to mnemonic)```
