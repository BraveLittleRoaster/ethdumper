from ethdumper.setup_logger import ConsoleLogger
import sys, time
import argparse
from tqdm import tqdm
from multiprocessing.dummy import Pool
from multiprocessing import cpu_count
from urllib3.connectionpool import xrange
from base64 import b64encode
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, UnexpectedAlertPresentException
from bs4 import BeautifulSoup
import requests
import json


def shard(input_list, n):
    """ Yield successive n-sized chunks from an input list."""
    for i in xrange(0, len(input_list), n):
        yield input_list[i:i + n]


def setup_driver():

    fp = webdriver.FirefoxProfile()
    # Options for proxy.
    if http_proxy or https_proxy or socks_proxy:

        if proxy_uname:
            # Setup the login information if the proxy uses auth.
            credentials = f"{proxy_uname}:{proxy_pass}"
            credentials = b64encode(credentials.encode('utf-8')).decode('utf-8')
            fp.set_preference("extensions.closeproxyauth.authtoken", credentials)

        if http_proxy:
            proxy_host = http_proxy.split(":")[0]
            proxy_port = int(http_proxy.split(":")[1])
        if https_proxy:
            proxy_host = https_proxy.split(":")[0]
            proxy_port = int(https_proxy.split(":")[1])
        if socks_proxy:
            proxy_host = socks_proxy.split(":")[0]
            proxy_port = int(socks_proxy.split(":")[1])
            fp.set_preference("network.proxy.socks", proxy_host)
            fp.set_preference("network.proxy.socks_port", proxy_port)

        else:

            fp.set_preference("network.proxy.http", proxy_host)
            fp.set_preference("network.proxy.http_port", proxy_port)
            fp.set_preference("network.proxy.https", proxy_host)
            fp.set_preference("network.proxy.https_port", proxy_port)
            fp.set_preference("network.proxy.ssl", proxy_host)
            fp.set_preference("network.proxy.ssl_port", proxy_port)
            fp.set_preference("network.proxy.ftp", proxy_host)
            fp.set_preference("network.proxy.ftp_port", proxy_port)

        fp.set_preference("network.proxy.type", 1)
        fp.update_preferences()

    # Options for automatically downloading shit.
    fp.set_preference("browser.download.folderList", 2)
    fp.set_preference("browser.download.manager.showWhenStarting", False)
    fp.set_preference("browser.download.dir", "./")
    fp.set_preference("browser.helperApps.neverAsk.openFile", "text/csv,text/plain,application/comma-separated-values,application/x-gzip,application/octet-stream")
    fp.set_preference("browser.helperApps.neverAsk.saveToDisk", "text/csv,text/plain,application/comma-separated-values,application/x-gzip,application/octet-stream")
    fp.update_preferences()

    logger.debug(f"Setting up driver with: HTTP Proxy: {http_proxy}, SSL Proxy: {https_proxy}, SOCKS proxy: {socks_proxy}, Proxy Uname: {proxy_uname}, Proxy Pass: {proxy_pass}")
    driver = webdriver.Firefox(firefox_profile=fp)
    return driver


def pad_zeros(privKey):

    # Wallets must be 64 chars. If they're less, pad them out with 0s.
    if len(privKey) < 64:
        key = "0" * (64-len(privKey)) + privKey
    elif len(privKey) > 65:
        key = None  # Key is invalid!
    else:
        key = privKey

    return key


def session_init(driver):
    # When the driver first connects to myetherwallet, it has a popup.
    url = "https://www.myetherwallet.com/"

    try:
        driver.get(url)
        # Click the stupid "Welcome to MEW" button if its there.
        onward_btn_xpath = "/html/body/div[1]/div[3]/div[1]/div/div/div/div/div/div[2]/button"
        onward_button = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, onward_btn_xpath))
        )
        onward_button.click()
        return True
    except Exception as e:
        logger.debug(f"Welcome to MEW button not detected: {e}")
        return False


def parse_page(html, privKey):

    soup = BeautifulSoup(html, 'html.parser')
    eth_balance_div = soup.find("div", {"class": "balance-text"})
    eth_balance = eth_balance_div.text
    eth_balance = eth_balance.replace("ETH", "")  # Strip out 'ETH', we know what it is.
    eth_balance = eth_balance.replace(" ", "")  # Strip out whitespace.
    eth_usd_value = "{:.2f}".format(float(eth_balance) * token_exchange_rate['ETH'])

    if float(eth_usd_value) > 0:
        logger.success(f"Found {eth_balance} (${eth_usd_value}) ETH on {privKey}")
    else:
        logger.debug(f"Found {eth_balance} (${eth_usd_value}) ETH on {privKey}")

    token_table_div = soup.find("div", {"class": "token-table-container"})
    token_table = token_table_div.find_all("table")
    for table in token_table:
        rows = table.find_all("tr")
        for row in rows:
            ticker = row.find("span").text
            tds = row.find_all("td")
            token_balance = tds[1].text
            token_balance = token_balance.replace("...", "")  # Strip ellipses
            token_balance = token_balance.replace(" ", "")  # strip whitespace
            ex_rate = get_token_price(ticker)
            if ex_rate:
                token_usd_value = "{:.2f}".format(float(token_balance) * ex_rate)
            else:
                token_usd_value = 0
            if float(token_usd_value) > 0:
                logger.success(f"Found {token_balance} {ticker} on {privKey}. USD value: (${token_usd_value})")
            else:
                logger.debug(f"Found {token_balance} {ticker} on {privKey}. USD value: (${token_usd_value})")


def get_token_price(token):
    """
    Search this token ticker on Cryptocompare and return its USD balance. Not all pairs will have values, and some may
    be misrepresented. For example there are two different tokens with "LIGHT" as the designator. If no exchange rate
    is found, it will update the global token_exchange_rate dict with the token-usd pairing.

    :param token: Token ticker. Ex: USDT
    :return: The exchange rate of each token to $USD.
    """

    if token not in token_exchange_rate:

        api_url = f"https://min-api.cryptocompare.com/data/price?fsym={token}&tsyms=USD"
        req = requests.get(api_url)
        price_per_token = json.loads(req.content)
        logger.spam(f"Cryptocompare API {token}: ${price_per_token}")
        usd_price = price_per_token.get('USD')
        token_exchange_rate[token] = usd_price

    else:
        usd_price = token_exchange_rate[token]

    return usd_price


def do_login(driver, privKey):

    url = "https://www.myetherwallet.com/"
    padded_key = pad_zeros(privKey)

    if padded_key:
        # Yeah its kind of redundant on the first login, but every other login will allow a logout of the previous key by getting this page.
        driver.get(url)
    else:
        logger.warn(f"Invalid private key length: {privKey}! Skipping.")
        return False

    try:

        # Click the "Access My Wallet" card.
        access_wallet_card_xpath = "/html/body/div[1]/div[3]/div[1]/div/div/div[2]/a[2]"
        access_wallet_card = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.XPATH, access_wallet_card_xpath))
            )
        access_wallet_card.click()

        # Click the "Software" card.
        software_card_xpath = "/html/body/div[1]/div[3]/div[1]/div[6]/div/div[2]/button[4]"
        software_card = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.XPATH, software_card_xpath))
            )
        software_card.click()

        # Click the "Private Key" button option.
        priv_key_btn_xpath = "/html/body/div[1]/div[3]/div[1]/div[2]/div[1]/div/div/div/div[2]/div[1]/div[1]/div[3]/div"
        priv_key_btn = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.XPATH, priv_key_btn_xpath))
            )
        priv_key_btn.click()

        # Click the "Continue" button.
        continue_btn_xpath = "/html/body/div[1]/div[3]/div[1]/div[2]/div[1]/div/div/div/div[2]/div[2]/div/div/button[2]"
        continue_btn = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.XPATH, continue_btn_xpath))
            )
        continue_btn.click()

        # Punch in the private key
        priv_key_input_xpath = "/html/body/div[1]/div[3]/div[1]/div[2]/div[1]/div/div/div/div[2]/div[1]/div[1]/input"
        priv_key_input = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, priv_key_input_xpath))
        )
        priv_key_input.send_keys(padded_key)

        # Access the wallet. If the wallet is invalid, it should timeout here and skip.
        access_wallet_btn_xpath = "/html/body/div[1]/div[3]/div[1]/div[2]/div[1]/div/div/div/div[2]/div[1]/div[2]/div"
        access_wallet_btn = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, access_wallet_btn_xpath))
        )
        access_wallet_btn.click()

        # Something to look for after logging in before dumping the HTML.
        balance_block_xpath = "/html/body/div[1]/div[3]/div[9]/div[2]/div/div[2]/div/div[2]"
        balance_block = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.XPATH, balance_block_xpath))
        )
        # Wait for the tokens to load by waiting for the fucking spinner to stop spinning. When it does, the HTML is ready to dump.

        token_loading_spinner = "/html/body/div[1]/div[3]/div[9]/div[2]/div/div[5]/div/div[2]/div[1]/div[3]/div[1]"
        token_spinner = WebDriverWait(driver, 20).until(
            EC.invisibility_of_element((By.XPATH, token_loading_spinner))
        )

        token_container_xpath = "/html/body/div[1]/div[3]/div[9]/div[2]/div/div[5]/div/div[2]/div[1]/div[3]"
        token_container = WebDriverWait(driver, 20).until(
            EC.visibility_of_element_located((By.XPATH, token_container_xpath))
        )

        return driver.page_source

    except Exception as e:
        logger.warn(f"Worker failed to login with {padded_key}. Error: {e}. Skipping...")
        return False


def run_worker(chunked_work):

    driver = setup_driver()
    logger.debug(f"Worker thread started, handling {len(chunked_work)} tasks and fetching current ETH-USD exchange rate.")
    eth_usd = get_token_price("ETH")
    logger.spam(f"Current ETH-USD exchange rate is {eth_usd}")
    session_init(driver)
    for privKey in chunked_work:
        html = do_login(driver, privKey=privKey)
        if html:
            parse_page(html, privKey)
        #pbar.update()


def main():

    parser = argparse.ArgumentParser('MyEtherWallet Dumper')
    # Switched args
    parser.add_argument("-v", dest="verbose", action='count', default=1,
                        help="Enable verbose output. Ex: -v, -vv, -vvv")
    parser.add_argument("-iL", "--input-list", dest="inlist", help="Use a list of private keys.")
    parser.add_argument("-k", "--key", dest="singlekey", help="Use only a single private key.")
    parser.add_argument("-w", "--workers", dest="workers", default=12, help="Number of selenium workers to use. Default: 12")

    proxy_settings = parser.add_argument_group("Proxy Settings")
    proxy_settings.add_argument("--http-proxy", dest="http_proxy", default=None, help="HTTP Proxy for Selenium. Ex: 127.0.0.1:8080")
    proxy_settings.add_argument("--https-proxy", dest="https_proxy", default=None, help="HTTPS Proxy for Selenium. Ex: 127.0.0.1:8080")
    proxy_settings.add_argument("--socks-proxy", dest="socks_proxy", default=None, help="SOCKS Proxy for Selenium. Ex: 127.0.0.1:9050")
    proxy_settings.add_argument("--proxy-user", dest="proxy_uname", default=None, help="Username for proxy authentication.")
    proxy_settings.add_argument("--proxy-pass", dest="proxy_pass", default=None, help="Password for proxy authentication.")

    tx_opts = parser.add_argument_group("Transfer options")
    tx_opts.add_argument("--to-wallet", dest="rxwallet", help="Dump everything in the wallet to this address.")
    tx_opts.add_argument("--fill-gas", dest="txneedsgas", action="store", help="If the TX wallet doesn't have the required gas, fill it first from this private key.")

    args = parser.parse_args()

    global vlevel
    vlevel = args.verbose
    global logger
    logger = ConsoleLogger(vlevel)
    global pbar
    global workers
    workers = int(args.workers)
    global http_proxy
    http_proxy = args.http_proxy
    global https_proxy
    https_proxy = args.https_proxy
    global socks_proxy
    socks_proxy = args.socks_proxy
    global proxy_uname
    proxy_uname = args.proxy_uname
    global proxy_pass
    proxy_pass = args.proxy_pass

    global token_exchange_rate
    token_exchange_rate = dict()

    if args.inlist:
        f = open(args.inlist, 'r')
        keys = list((l.rstrip("\n") for l in f))
    elif args.singlekey:
        keys = [args.singlekey]
    else:
        logger.error("Please specify either --key or -iL to input a single or list of private keys to check.")
        sys.exit(1)

    pbar = tqdm(total=len(keys), unit=" searches", maxinterval=0.1, mininterval=0)

    chunk_size = int(len(keys)/workers)
    if chunk_size == 0:
        chunk_size = 1
    logger.spam(f"Using shard size: {chunk_size}")
    try:
        logger.info(f'Start time: {time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())}')
        p = Pool(workers)
        for _ in p.imap_unordered(run_worker, shard(keys, chunk_size)):
            pass
    except KeyboardInterrupt:
        pbar.close()
        logger.warning("Keyboard interrupt. Please wait, cleaning up...")
    #finally:
        #pbar.close()
        #logger.info(f'End time: {time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())}')


if __name__ == "__main__":

    main()
