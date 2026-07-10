This application creates a user interface that combines a lot of the previous code that was written.
The demo is uploaded as a video along with the code files

Reaction prep
- The gcode writer and the connection to the syringe pump/CNC are now connected, so there is no need to make a .csv file and upload the gcode separately (all of this is in one window)
- You can generate a gcode file from a visual well plate or you can upload an old .csv or gcode file and it will recognize it
- You can use a preset well plate (384 wells, 96 wells, etc.) or make your own well plate and save it as a preset
- You can also save 'reactions' as presets (although I think saving them as .csv files is the same thing, it's just more accessible if you're doing the same thing all the time)
- You can easily view the settings (dwell time, CNC settings) and play around with them.
- You can also choose a default folder to save the file in and it saves it with each time you open it (via the json file)

Running reactions
- The code tells you which droplet # it is currently in the process of making & provides a time estimate to completion (useful for longer runs)
- The time estimate is based on the dwell time & CNC speed settings
- New progress bar (fun loading screen -> I just picked a few random gifs that are uploaded in the loading_images folder. You can change them but the names of the files need to be changed)

There are still a lot of changes that need to be made

Daria Rudykh
