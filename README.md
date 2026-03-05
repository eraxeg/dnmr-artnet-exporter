cp ~/dnmr-monitoring/artnet-exporter/com.parreno.artnet-exporter.plist \
      ~/Library/LaunchAgents/

launchctl unload ~/Library/LaunchAgents/com.parreno.artnet-exporter.plist
launchctl load ~/Library/LaunchAgents/com.parreno.artnet-exporter.plist
launchctl start ~/Library/LaunchAgents/com.parreno.artnet-exporter.plist

