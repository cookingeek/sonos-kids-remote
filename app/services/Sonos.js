let { DeviceDiscovery } = require('sonos');
const Regions = require('sonos').SpotifyRegion
var defaultDevice = null;

class Sonos {
  constructor(myIp) {
    console.log("Init Sonos");
    if (myIp != null && myIp != undefined) {
      this.myIp = myIp;
    }

    //discover default device
    DeviceDiscovery((device) => {
      device.deviceDescription().then((model) => {
        if (model.roomName == properties.get('sonos.base')) {
          device.setSpotifyRegion(Regions.EU);
          defaultDevice = device;
          console.log("Set default device: " + model.roomName);
        }
      });
    });
  }

  play(cardId) {
    defaultDevice.play("http://" + this.myIp + ":3000/localmusic/dean.mp3");
  }

  stop() {

  }

  volumeUp() {

  }

  volumeDown() {

  }

  setSonos() {

  }

  createGroup() {

  }
};

module.exports = Sonos;