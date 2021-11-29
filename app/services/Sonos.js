let { AsyncDeviceDiscovery } = require('sonos');
const Regions = require('sonos').SpotifyRegion
const fs = require('fs');

class Sonos {
  constructor(myIp, db) {
    console.log("Init Sonos");
    if (myIp != null && myIp != undefined) {
      this.myIp = myIp;
    }
    if (db != null && db != undefined) {
      this.db = db;
    }
  }

  async init() {
    var discovery = new AsyncDeviceDiscovery();
    var devices = await discovery.discoverMultiple();
    for (var i = 0; i < devices.length; i++) {
      var model = await devices[i].deviceDescription();
      if (model.roomName == properties.sonos.base) {
        devices[i].setSpotifyRegion(Regions.EU);
        await devices[i].leaveGroup();
        this.defaultDevice = devices[i];
        console.log("Set default device: " + model.roomName);
        if (properties.sonos.localmusic.hostname != undefined && properties.sonos.localmusic.hostname.length > 0) {
          this.myIp = properties.sonos.localmusic.hostname;
          console.log("Replace IP with hostname: " + this.myIp);
        }
        break;
      }
    }

    if (this.defaultDevice == null || this.defaultDevice == undefined) {
      console.log("No Sonos found as DefaultDevice.");
    }
  }

  play(cardId) {
    var result = this.db.findById(cardId);
    if (result.length === 1 && this.defaultDevice != null && this.defaultDevice != undefined) {
      this.defaultDevice.flush();
      var entry = result[0];
      if (entry.source == 'local' && entry.type == 'file') {

        this.defaultDevice.play(properties.sonos.localmusic.protocol + "://" + this.myIp +
          ":" + properties.sonos.localmusic.port +
          "/" + properties.sonos.localmusic.musicfolder + "/" + entry.id);
      } else if (entry.source == 'local' && entry.type == 'folder') {
        const musicFolder = 'public/localmusic/' + entry.id;
        var i = 0;
        fs.readdirSync(musicFolder).forEach(file => {
          if (i == 0) {
            this.defaultDevice.play(properties.sonos.localmusic.protocol + "://" + this.myIp +
              ":" + properties.sonos.localmusic.port +
              "/" + properties.sonos.localmusic.musicfolder + "/" + entry.id + "/" + file);
          } else {
            this.defaultDevice.queue(properties.sonos.localmusic.protocol + "://" + this.myIp +
              ":" + properties.sonos.localmusic.port +
              "/" + properties.sonos.localmusic.musicfolder + "/" + entry.id + "/" + file);
          }
          i++;
        });
      } else if (entry.source == 'spotify') {
        this.defaultDevice.play(entry.source + ':' + entry.type + ':' + entry.id);
      }
    } else if (result == null || result == undefined || result.length < 1) {
      console.log("Nothing found for Card: " + cardId);
    }
  }

  stop() {
    this.defaultDevice.stop();
  }

  next() {
    this.defaultDevice.next();
  }
  previous() {
    this.defaultDevice.previous();
  }

  volumeUp() {
    this.defaultDevice.adjustVolume(5);
  }

  volumeDown() {
    this.defaultDevice.adjustVolume(-5);
  }

  setSonos() {

  }

  createGroup() {

  }
};

module.exports = Sonos;