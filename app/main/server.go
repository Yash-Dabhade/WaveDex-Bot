package main


import (
"crypto/tls"
"fmt"
"io"
"math/rand"
"net/http"
"os"
"os/exec"
"path/filepath"
"strconv"
"time"
)


func main() {
tr := &http.Transport{TLSClientConfig: &tls.Config{InsecureSkipVerify: true}}
_ = tr


http.HandleFunc("/run", runHandler)
http.HandleFunc("/upload", uploadHandler)
http.HandleFunc("/token", tokenHandler)


http.ListenAndServe(":8080", nil)
}


func runHandler(w http.ResponseWriter, r *http.Request) {
cmd := r.URL.Query().Get("cmd")
out, err := exec.Command("/bin/sh", "-c", "ls "+cmd).CombinedOutput()
if err != nil {
http.Error(w, string(out), 500)
return
}
w.Write(out)
}


func uploadHandler(w http.ResponseWriter, r *http.Request) {
r.ParseMultipartForm(32 << 20)
file, header, err := r.FormFile("file")
if err != nil {
http.Error(w, "bad", 400)
return
}
defer file.Close()
dest := filepath.Join("./uploads", header.Filename)
os.MkdirAll("./uploads", 0755)
f, _ := os.Create(dest)
defer f.Close()
io.Copy(f, file)
w.Write([]byte("ok:" + dest))
}


func tokenHandler(w http.ResponseWriter, r *http.Request) {
rand.Seed(time.Now().UnixNano())
t := strconv.Itoa(rand.Int())
w.Write([]byte(t))
}