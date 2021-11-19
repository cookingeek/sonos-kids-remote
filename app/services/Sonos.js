let { DeviceDiscovery } = require('sonos');
const Regions = require('sonos').SpotifyRegion

class Sonos {
  constructor(myIp, db) {
    console.log("Init Sonos");
    if (myIp != null && myIp != undefined) {
      this.myIp = myIp;
    }
    if (db != null && db != undefined) {
      this.db = db;
    }

    //discover default device
    DeviceDiscovery((device) => {
      device.deviceDescription().then((model) => {
        if (model.roomName == properties.sonos.base) {
          device.setSpotifyRegion(Regions.EU);
          this.defaultDevice = device;
          console.log("Set default device: " + model.roomName);
        }
      });
    });
  }

  play(cardId) {
    this.db.findById(cardId, (function (error, result) {
      if (result.length === 1) {
        this.defaultDevice.flush();
        var entry = result[0];
        if (entry.source == 'local' && entry.type == 'file') {
          this.defaultDevice.play(properties.sonos.localmusic.protocol + "://" + this.myIp +
            ":" + properties.sonos.localmusic.port +
            "/" + properties.sonos.localmusic.musicfolder + "/" + entry.name);
        } else if(entry.source == 'local' && entry.type == 'folder'){

        }else if(entry.source == 'spotify' && entry.type == 'album'){

        }else if(entry.source == 'spotify' && entry.type == 'playlist'){

        }
      }
    }).bind(this));
  }

  stop() {
    this.defaultDevice.stop();
  }
  
  next() {
    this.defaultDevice.next();
  }
  previous(){
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