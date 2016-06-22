#!/usr/bin/env python2
import os, logging, sys, requests, urlparse, shutil, re, threading, posixpath, argparse, atexit, random, socket, time, hashlib, pickle, signal, subprocess
try:
	import config
except ImportError:
	config = None


#config
output_dir = './bing' #default output dir
adult_filter = True #Do not disable adult filter by default
pool_sema = threading.BoundedSemaphore(value = 20) #max number of download threads
bingcount = 35 #default bing paging
socket.setdefaulttimeout(3)

in_progress = []
tried_urls = []
skip_urls = []
finished_keywords = []
failed_urls = []
domainhits = {}
urlopenheader={ 'User-Agent' : 'Mozilla/5.0 (X11; Fedora; Linux x86_64; rv:42.0) Gecko/20100101 Firefox/42.0'}

# Logging
FORMAT = '%(asctime)-15s %(message)s'
logging.basicConfig(level=logging.WARNING, format=FORMAT)


def download(url,output_dir,retry=False):
	global tried_urls, failed_urls, successful_urls, skip_urls
	url_hash=hashlib.sha224(url.encode('utf-8')).digest()
	if url_hash in tried_urls:
		return
	elif url_hash in skip_urls:
		return
	urlbits = urlparse.urlparse(url)
	path = urlbits.path
	domain = urlbits.netloc

	# Check for file extension and domain counter
	if config:
		if config.domainlimit:
			count = domainhits.get(domain)
			if count and count >config.domainlimit:
				#print("Domain limit reached " + domain)
				#failed_urls.append((url, output_dir))
				#logging.warning('"Domain limit reached: {}'.format(domain))
				skip_urls.append(url_hash)
				return -1
		if config.extensions:
			ext = os.path.splitext(path)[1].lower()
			if ext not in config.extensions:
				#failed_urls.append((url, output_dir))
				#print 'Ignored file: {}'.format(ext)
				skip_urls.append(url_hash)
				return -1
	filename = posixpath.basename(path)
	pool_sema.acquire()
	if len(filename)>40:
		filename=filename[:36]+filename[-4:]
	while os.path.exists(output_dir + '/' + filename):
		filename = str(random.randint(0,1000)) + filename
	in_progress.append(filename)
	try:
		#request=urllib.request.Request(url,None,urlopenheader)
		#image=urllib.request.urlopen(request).read()
		response = requests.get(url, headers=urlopenheader, timeout=10)
		if response.status_code == 200:
			fpath = output_dir + '/' + filename
			with open(fpath, 'wb+') as f:
				for chunk in response.iter_content():
					f.write(chunk)
		else:
			raise Exception('Bad Reuqest: {} \n{}'.format(response.status_code, response.reason))
		in_progress.remove(filename)
		if retry:
			print('Retry OK '+ filename)
		else:
			print("OK " + filename)
		tried_urls.append(url_hash)
	except Exception as e:
		print e
		domainhits[domain] = domainhits.get(domain, 0) - 1 #Failure, decrement domain hits
		if retry:
			print('Retry Fail ' + filename)
			logging.info('Retry Failed: {}'.format(url))
		else:
			print("FAIL " + filename)
			logging.warning('Failed: {}'.format(url))
			failed_urls.append((url, output_dir))
		pool_sema.release()
		return
	logging.warning('Success: {} - {}'.format(url, output_dir + '/' + filename))
	pool_sema.release()

def removeNotFinished():
	for filename in in_progress:
		try:
			os.remove(output_dir + '/' + filename)
		except:
			pass

def fetch_images_from_keyword(keyword,output_dir):
	current = 1
	last = ''
	while True:
		params = {'q': keyword, 'async':'content', 'first': str(current), 'adlt':adlt}
		request_url = 'https://www.bing.com/images/async'
		#request_url='https://www.bing.com/images/async?q=' + parse_quote_plus(keyword) + '&async=content&first=' + str(current) + '&adlt=' + adlt
		response=requests.get(request_url, params=params, headers=urlopenheader)
		html = response.text
		links = re.findall('imgurl:&quot;(.*?)&quot;',html)
		try:
			if links[-1] == last:
				break
			last = links[-1]
			current += bingcount
			for link in links:
				domain = urlbits = urlparse.urlparse(link).netloc
				domainhits[domain] = domainhits.get(domain, 0) + 1 # Add domain hit here to avoid race condition
				t = threading.Thread(target = download,args = (link,output_dir))
				#t.daemon = True
				t.start()
		except IndexError:
			print('No search results for "{0}"'.format(keyword))
			return False
		time.sleep(0.1)
	return True

def backup_history(*args):
	download_history=open(output_dir + '/download_history.pickle','wb')
	pickle.dump(tried_urls,download_history)
	pickle.dump(skip_urls,download_history)
	pickle.dump(finished_keywords, download_history)
	pickle.dump(domainhits, download_history)
	download_history.close()
	print('history_dumped')
	if args:
		exit(0)

if __name__ == "__main__":
	atexit.register(removeNotFinished)
	parser = argparse.ArgumentParser(description = 'Bing image bulk downloader')
	parser.add_argument('-s', '--search-string', help = 'Keyword to search', required = False)
	parser.add_argument('-f', '--search-file', help = 'Path to a file containing search strings line by line', required = False)
	parser.add_argument('-o', '--output', help = 'Output directory', required = False)
	#parser.add_argument('-e', '--ext', help = 'File Extentions', required = False)
	parser.add_argument('--filter', help = 'Enable adult filter', action = 'store_true', required = False)
	parser.add_argument('--no-filter', help=  'Disable adult filter', action = 'store_true', required = False)
	args = parser.parse_args()
	if (not args.search_string) and (not args.search_file):
		parser.error('Provide Either search string or path to file containing search strings')
	if args.output:
		output_dir = args.output
	if not os.path.exists(output_dir):
		os.makedirs(output_dir)
	output_dir_origin = output_dir
	signal.signal(signal.SIGINT, backup_history)
	file_handler = logging.FileHandler(output_dir + os.sep + 'urls.log')
	file_handler.setFormatter(logging.Formatter(FORMAT))
	logging.getLogger().addHandler(file_handler)
	try:
		download_history=open(output_dir + '/download_history.pickle','rb')
		tried_urls=pickle.load(download_history)
		skip_urls=pickle.load(download_history)
		finished_keywords=pickle.load(download_history)
		domainhits=pickle.load(download_history)
		download_history.close()
	except (OSError, IOError):
		tried_urls=[]
	if adult_filter:
		adlt = ''
	else:
		adlt = 'off'
	if args.no_filter:
		adlt = 'off'
	elif args.filter:
		adlt = ''
	#if args.ext:
	#	print args.ext
	if args.search_string:
		keyword = args.search_string
		fetch_images_from_keyword(args.search_string,output_dir)
	elif args.search_file:
		try:
			inputFile=open(args.search_file)
		except (OSError, IOError):
			print("Couldn't open file {}".format(args.search_file))
			exit(1)
		for keyword in inputFile.readlines():
			keyword_hash=hashlib.sha224(keyword.strip().encode('utf-8')).digest()
			if keyword_hash in finished_keywords:
				print('"{0}" Already downloaded'.format(keyword.strip()))
				continue
			output_dir = output_dir_origin + '/' + keyword.strip().replace(' ','_')
			if not os.path.exists(output_dir):
				os.makedirs(output_dir)
			if fetch_images_from_keyword(keyword,output_dir):
				finished_keywords.append(keyword_hash)
				for failed_url in failed_urls:
					t = threading.Thread(target = download,args = (failed_url[0],failed_url[1],True))
					#t.daemon=True
					t.start()
				failed_urls=[]
			backup_history()
		inputFile.close()
