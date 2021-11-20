module.exports = {
    name: "Jakobs Sonos Controller",
    sonos: {
        base: 'Move',
        localmusic: {
            port: '3000',
            musicfolder: 'localmusic',
            protocol: 'http'
        }
    },
    webserver: {
        //interface: 'wlan0'
        interface: 'en0'
    },
    gpio: {
        next: '',
        back: '', volumeUp: '',
        volumeDown: ''
    },
    db:{
        filename: 'database.db'
    }
};