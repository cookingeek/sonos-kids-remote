let { AsyncDeviceDiscovery } = require('sonos');
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

  }

  async init() {
    //discover default device
    var discovery = new AsyncDeviceDiscovery();//(device) => {
    var devices = await discovery.discoverMultiple();
    for(var i = 0; i < devices.length; i++){
      var model = await devices[i].deviceDescription();//.then((model) => {
      if (model.roomName == properties.sonos.base) {
        devices[i].setSpotifyRegion(Regions.EU);
        this.defaultDevice = devices[i];
        console.log("Set default device: " + model.roomName);
        break;
      }
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

      } else if (entry.source == 'spotify' && entry.type == 'album') {

      } else if (entry.source == 'spotify' && entry.type == 'playlist') {

      }
      
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