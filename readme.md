# run with
add your paths to images and annotations in `app.py` and run
```
# local
uvicorn app:app --host 127.0.0.1 --port 8001

# http
uvicorn app:app --host 0.0.0.0 --port 8018 --reload

# https
uvicorn app:app --host 0.0.0.0 --port 8018 --reload --ssl-keyfile key.pem --ssl-certfile cert.pem


```

# done
- baby app
- visualize bounding boxes
- turn them on and off
- add zoom and panning
- make faster (if possible)
- add edits
- show counts
- export
- add timestamps
- fix image path when saving
- save annotations when going to a new image

# to-do
