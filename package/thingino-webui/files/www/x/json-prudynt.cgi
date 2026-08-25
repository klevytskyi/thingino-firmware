#!/bin/sh
# BusyBox httpd CGI for JSON API
# Expects request body (application/json)

# Check authentication
. /var/www/x/auth.sh
require_auth

send_headers() {
	echo "Content-Type: application/json"
	echo "Connection: close"
	echo
}

# ---------------------------------------------------------------------------
# raptor fallback
#
# Cameras running the raptor streamer have no prudyntctl, so every audio (and
# streamer) page used to fail: the handler emitted headers and then nothing,
# and an empty body makes the browser's response.json() throw "Unexpected end
# of JSON input" - which reads like a broken save rather than "wrong streamer".
#
# The pages speak prudynt's parameter names, so translate them to raptor's
# [audio] keys and drive raptorctl instead. Anything without a raptor
# equivalent (ALC gain, AGC compression/target, force stereo) is simply left
# out of the reply, which the UI already renders as an unavailable control.
# ---------------------------------------------------------------------------

# prudynt name : raptor key
RAPTOR_AUDIO_MAP="
mic_enabled:enabled
mic_format:codec
mic_sample_rate:sample_rate
mic_bitrate:bitrate
mic_vol:volume
mic_gain:gain
mic_agc_enabled:agc_enabled
mic_high_pass_filter:hpf_enabled
mic_noise_suppression:ns_enabled
spk_enabled:ao_enabled
spk_vol:ao_volume
spk_gain:ao_gain
spk_sample_rate:ao_sample_rate
"

# Read "key = value" from `raptorctl config get audio` into a lookup file once,
# rather than shelling out per parameter.
raptor_audio_snapshot() {
	raptorctl config get audio 2>/dev/null \
		| sed -n 's/^[[:space:]]*\([a-z0-9_]*\)[[:space:]]*=[[:space:]]*\(.*\)$/\1=\2/p'
}

# $1 = raptor key, $2 = snapshot file
raptor_audio_value() {
	sed -n "s/^$1=//p" "$2" | head -1
}

# Extract a JSON scalar for "key" from the request body. Emits nothing when the
# key is absent or explicitly null, which is how the UI asks for a read.
json_scalar() {
	sed -n "s/.*\"$1\"[[:space:]]*:[[:space:]]*\([^,}]*\).*/\1/p" "$2" \
		| head -1 | sed 's/^[[:space:]]*//; s/[[:space:]]*$//; s/^"//; s/"$//'
}

raptor_handle() {
	body="$1"
	changed=0

	# Apply any writes first.
	echo "$RAPTOR_AUDIO_MAP" | while read -r pair; do
		[ -n "$pair" ] || continue
		pname=${pair%%:*}
		rkey=${pair##*:}
		grep -q "\"$pname\"" "$body" || continue
		val=$(json_scalar "$pname" "$body")
		[ -n "$val" ] && [ "$val" != "null" ] || continue
		raptorctl config set audio "$rkey" "$val" >/dev/null 2>&1
		echo "$rkey" >>"$body.written"
	done

	[ -s "$body.written" ] && changed=1

	# raptorctl's model: `config set` stages a value, `config save` writes the
	# running config to disk, and the audio daemon only picks new values up when
	# it restarts. Doing only the first two leaves the page showing the OLD
	# number after a successful save, which reads as "it did not work".
	if [ "$changed" = "1" ] || grep -q '"save_config"' "$body"; then
		raptorctl config save >/dev/null 2>&1
	fi

	# The page already signals its intent with action.restart_thread; honour it
	# by restarting just the audio daemon rather than the whole streamer, so
	# video and RTSP clients are undisturbed.
	if [ "$changed" = "1" ]; then
		raptorctl rad restart >/dev/null 2>&1
		# rad needs a moment before it reports the new running values.
		sleep 4
	fi

	snap=$(mktemp /tmp/raptor_audio.XXXXXX)
	raptor_audio_snapshot >"$snap"

	send_headers
	printf '{"audio":{'
	first=1
	for pair in $RAPTOR_AUDIO_MAP; do
		pname=${pair%%:*}
		rkey=${pair##*:}
		val=$(raptor_audio_value "$rkey" "$snap")
		[ -n "$val" ] || continue
		[ "$first" = "1" ] || printf ','
		first=0
		case "$val" in
			true | false) printf '"%s":%s' "$pname" "$val" ;;
			'' | *[!0-9-]*) printf '"%s":"%s"' "$pname" "$val" ;;
			*) printf '"%s":%s' "$pname" "$val" ;;
		esac
	done
	printf '},"streamer":"raptor"}\n'

	rm -f "$snap" "$body.written"
}

if ! command -v prudyntctl >/dev/null 2>&1; then
	if command -v raptorctl >/dev/null 2>&1; then
		req=$(mktemp /tmp/prudynt_req.XXXXXX)
		if [ -n "$CONTENT_LENGTH" ]; then
			dd bs=1 count="$CONTENT_LENGTH" 2>/dev/null >"$req"
		else
			cat >"$req"
		fi
		raptor_handle "$req"
		rm -f "$req"
		exit 0
	fi

	echo "Status: 501 Not Implemented"
	send_headers
	printf '{"error":{"code":501,"message":"neither prudyntctl nor raptorctl is available on this camera"}}\n'
	exit 0
fi

send_headers

# Read exactly CONTENT_LENGTH bytes if provided; otherwise read all stdin
if [ -n "$CONTENT_LENGTH" ]; then
  dd bs=1 count="$CONTENT_LENGTH" 2>/dev/null | prudyntctl json -
else
  prudyntctl json -
fi
