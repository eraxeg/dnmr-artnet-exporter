ln -s ~/dnmr-monitoring/artnet-exporter/local.artnet-exporter.plist \
      ~/Library/LaunchAgents/

launchctl load ~/Library/LaunchAgents/local.artnet-exporter.plist

