#!/bin/sh
# BusyBox httpd CGI for JSON API
# Expects request body (application/json)

# Check authentication
. /var/www/x/auth.sh
require_auth

# Cameras running the raptor streamer have no prudyntctl at all. Without this
# guard the handler emitted headers and then nothing, because the missing
# command wrote no stdout - and an empty body makes the browser's
# response.json() throw "Unexpected end of JSON input", which reads like a
# broken save rather than "this page does not apply to this streamer".
if ! command -v prudyntctl >/dev/null 2>&1; then
	echo "Status: 501 Not Implemented"
	echo "Content-Type: application/json"
	echo "Connection: close"
	echo
	printf '{"error":{"code":501,"message":"prudyntctl is not available on this camera (streamer is not prudynt)"}}\n'
	exit 0
fi

echo "Content-Type: application/json"
echo "Connection: close"
echo

# Read exactly CONTENT_LENGTH bytes if provided; otherwise read all stdin
if [ -n "$CONTENT_LENGTH" ]; then
  dd bs=1 count="$CONTENT_LENGTH" 2>/dev/null | prudyntctl json -
else
  prudyntctl json -
fi
