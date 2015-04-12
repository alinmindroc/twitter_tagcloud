#!/usr/bin/env python
import tweepy
import time
import re
import sys
import json
import signal
import redis
import os

#twitter auth keys
consumer_key ="JTFpeYyEkWSxWpiswY7QtJ7OH"
consumer_secret ="4RwpbR2WyUMDzEiZT1vWrv5YPM8uE2OZpsuRpIFQ6EtEwX6zRF"
access_token ="2491903045-uvJkmgD1BSx5QkiJqPU77nesyVhpY9KM2mshOoN"
access_token_secret ="quoULDWcS7afIr40JbbvtbU652rm28MH6BxY7PGiKRdRd"

stopwords_file_path = 'stopwords.txt'

redis_host = os.environ['REDIS_PORT_6379_TCP_ADDR']
redis_port = 6379

#start a global connection to a local redis server
try:
	redis_instance = redis.Redis(host=redis_host, port=redis_port)
	redis_instance.info()
except:
	print 'Could not connect to the redis server, exiting...'
	exit(-1)

#flush the current redis database so that results won't get mixed up between
#different runs of the script
redis_instance.flushdb()

#define a stream listener which will output and filter to file
class FilterListener(tweepy.StreamListener):
	def __init__(self):
		super(FilterListener, self).__init__()

	def on_status(self, status):
		#called when a new status is available, splits it in words and persist those
		#which are not stopwords
		words = re.findall(r'[a-zA-Z\']+', status.text)
		filtered_words = [w.lower() for w in words if w.lower() not in self.stopwords]
		self.persist(filtered_words)

	def set_stopwords(self, filename):
		#get a list of stopwords from a file
		stopwords_file = open(filename, 'r')
		self.stopwords = stopwords_file.read().splitlines()

	def persist(self, word_list):
		#save a list of words together with their occurence count to the redis cache
		for w in word_list:
			redis_instance.incr(w)

	def on_timeout(self):
		print 'timed out'

	def on_error(self, status_code):
		print 'error code %s' % status_code

def print_help(stream):
	print 'usage: ./wordcloud.py [seconds_of_streaming] [no_of_words]'
	stream.disconnect()
	sys.exit(-1)

if __name__ == '__main__':
	#get authorized to make requests
	auth = tweepy.OAuthHandler(consumer_key, consumer_secret)
	auth.set_access_token(access_token, access_token_secret)
	api = tweepy.API(auth)

	#instantiate the custom listener
	filterListener = FilterListener()
	filterListener.set_stopwords(stopwords_file_path)

	#initiate the stream using the filter listener
	myStream = tweepy.Stream(auth = api.auth, listener = filterListener)

	#this generates a stream of english tweets, it is asynchronous
	#so that it can be disconnected by the main thread after a specific delay.
	#Otherwise, it would just block the main thread and execution would halt
	#at this line
	myStream.sample(languages=['en'], async=True)

	#define and set a sigint handler which kills the stream thread first
	#and then quits from the main thread. Without this, the stream thread
	#would run forever
	def signal_handler(*args):
		myStream.disconnect()
		sys.exit(-1)

	signal.signal(signal.SIGINT, signal_handler)

	max_words = None

	#validate command line arguments
	if len(sys.argv) == 1:
		print_help(myStream)
	elif len(sys.argv) == 2:
		try:
			delay = int(sys.argv[1])
		except:
			print_help(myStream)
	elif len(sys.argv) == 3:
		try:
			delay = int(sys.argv[1])
			max_words = int(sys.argv[2])
		except:
			print_help(myStream)
	else:
		print_help(myStream)

	#gather tweets from the stream for <delay> seconds
	time.sleep(delay)

	#close the stream
	myStream.disconnect()

	#create a map based on the command line options
	json_list = []
	for key in redis_instance.keys():
		json_list.append({'word':key, 'count':int(redis_instance.get(key))})

	if max_words is None:
		json_obj = json_list
	else:
		#if the user wants just a part of the words, print those ordered by
		#occurence count and calculate the occurences of all the other words
		json_list.sort(lambda x, y: y['count'] - x['count'])
		other_count = sum(map(lambda x: x['count'], json_list[max_words:]))
		json_obj = json_list[:max_words]
		json_obj.append({'other_words': other_count})

	#dump the map as a json object
	print json.dumps(json_obj, indent=4)

