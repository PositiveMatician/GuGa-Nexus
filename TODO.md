In the Guga.installer

1. Add a new option list called Advanced options
Run as service foreground (here the installer skips all the systemd background processes and setup the guga to be ran as foreground service. And tell the user to use guga --start-server to start the server)

2. arrange the whole installation in stages , 
    all the installation which requires sudo will get its own stage and etc.
    mention the requirements of each of the installation stages
    if a stage doesn't gets it's required requirements, then it should be skipped and the user should be notified about the same. 
    Create a capabilities json in the config file whch keep track of the capability of the system , if a stage was skipped during installation then all its capabilites will be hidden , and if the user tries to install a stage manually then it should be installed.
    After a stage is installed, it should be marked as installed in the config file.
    
3. for sudo specifics , don't ask the user for sudo password in the ui.
    instead tell them all sudo stages are getting skipped , to use these rerun the installer with sudo 

