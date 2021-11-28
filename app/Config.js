module.exports = {
    name: "Jakobs Sonos Controller",
    sonos: {
        base: 'Kinderzimmer',
        localmusic: {
            port: '3000',
            musicfolder: 'localmusic',
            protocol: 'http',
            hostname: 'jakobsjukebox'
        }
    },
    webserver: {
        interface: 'wlan0'
        //interface: 'en0'
    },
    gpio: {
        next: '',
        back: '',
        volumeUp: '',
        volumeDown: '',
        led: ''
    },
    db:{
        filename: 'database.db'
    }
};