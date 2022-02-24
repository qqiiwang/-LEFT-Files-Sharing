from threading import Thread
from socket import *
import time
import os
import struct
import zipfile
import shutil
import argparse

# setting global variables
op_code = 10  # "op_code" is a sign to notify corresponding operations. "10" means scanning "share" folder
mtime = 0.00  # "mtime" is an abbreviation of "modified time".
size = 0  # "size" is used to record current file/folder size
name = ""  # "name" means the name of file/folder
scan_dict = {}  # "scan_dict" stores own result of scanning "share" folder
known_dict = {}  # "known_dict" saves the file sent to the other device with the modified time
known_size = {}  # "known_size" saves the file sent to the other device with file size
buffer_size = 10240


# Initializing a socket connection
# parse parameters
def _argparse():
    parser = argparse.ArgumentParser(description="This is description!")
    parser.add_argument('--ip', action='store', required=True, dest='ip',
                        help='The ip addresses of another computer')
    return parser.parse_args().ip


pc_port = 22007  # setting a fixed number as a port number
server_ip = _argparse()  # "server_ip" receives parsed parameter
server_socket = socket(AF_INET, SOCK_STREAM)
server_socket.bind(('', pc_port))
server_socket.listen(1)


# Check if it has a "share" folder, if not, create one.
def creat_folder():
    try:
        os.mkdir('share')
        print("Create a new 'share' folder!")
    except FileExistsError:
        print("'share' folder has already existed!")


# Scan what files are in the "share" folder and record them into a dict with their modified time
def scan_folder():
    scn_dict = {}  # record the file name and modified time
    scn_name = os.listdir("share")  # scan what files are in the "share" folder
    for f_name in scn_name:
        scn_dict[f_name] = os.path.getmtime(os.path.join("share", f_name))
    return scn_dict


# Pack related file information to transmit
def make_header(operation_code, mtime, c_size, file_name):
    header = struct.pack('!IdI', operation_code, mtime, c_size) + file_name.encode()
    return header


# Unpack related file information to assign values
def parse_header(header):
    r_opcode, r_time, r_size = struct.unpack("!IdI", header[:16])
    r_name = header[16:].decode()
    return r_opcode, r_time, r_size, r_name


# Compress the folder into a zip file
def compress_file(folder_name):
    z = zipfile.ZipFile(os.path.join(folder_name + '.zip'), 'w', zipfile.ZIP_DEFLATED)
    ls = os.listdir(os.path.join('share', folder_name))  # scan the files in the folder
    for sub_file in ls:
        z.write(os.path.join('share', folder_name, sub_file))
    z.close()

# Decompress the zip file into a folder
def decompress_file(folder_name):
    z = zipfile.ZipFile(folder_name + '.zip', 'r')
    z.extractall()
    z.close()

# ============================================================
# These are functions for "Client" part:
# Send file information to the other end
def client_send_msg(msg, port):
    """
    Build a client socket connection to send file information
    """
    sendingSocket = socket(AF_INET, SOCK_STREAM)
    sendingSocket.connect((server_ip, port))
    sendingSocket.send(msg)
    print('send', parse_header(msg), 'to', port)
    sendingSocket.close()


# Send specific file to the other end
def send_file(file, port):
    """
    Since this program may be killed in the process of sending files,
    so catch exceptions should be used here to make sure the file has been sent completely
    The buffer size cannot be set too big so a loop here helps to send
    """
    global buffer_size
    send_socket = socket(AF_INET, SOCK_STREAM)
    f = open(file, 'rb')
    try:
        send_socket.connect((server_ip, port))  # build a socket connection to send file
        file_data = f.read(buffer_size)
        while len(file_data) > 0:
            send_socket.send(file_data)
            file_data = f.read(buffer_size)
        send_socket.close()
        f.close()

    # if following situations happen, handle them here
    except (ConnectionRefusedError, TimeoutError, ConnectionResetError):
        print('Havn\'t not finished sending---' + file)


# Send specific folder to the other end
def send_folder(folder_name, port):
    compress_file(folder_name)  # compress the folder into a zip file which can help to transmit
    # send the compressed file and rename it with '.zip' attached to it
    send_file(os.path.join(folder_name + '.zip'), port)

# ===============================================================
# These are functions for "Server“ part
# Receive specific file from other end
def recv_file(name, rec_file_socket, mtime):
    with open(name, 'wb') as f:
        while True:
            bytes_read = rec_file_socket.recv(buffer_size)
            if not bytes_read:
                # nothing is received, file transmitting is done
                break
            f.write(bytes_read)

    shutil.move(name, os.path.join("share", name))  # move the file into "share" folder fastly
    # Once it received the whole file, send signal of op_code=3
    header = make_header(3, mtime, os.path.getsize(os.path.join("share", name)), name)
    Thread(target=client_send_msg, args=(header, pc_port)).start()


# Receive specific folder from other end
def receive_folder(fd_name, r_file_socket, mtime):
    global buffer_size
    with open(fd_name + '.zip', 'wb') as f:
        while True:
            bytes_read = r_file_socket.recv(buffer_size)
            if not bytes_read:
                # nothing is received, file transmitting is done
                break
            f.write(bytes_read)
    r_file_socket.close()

    decompress_file(fd_name)  # decompress zip file
    # Once it received the whole file and decompressed them, send signal of op_code=3
    header = make_header(3, mtime,
                         os.path.getsize(os.path.join("share", fd_name)), fd_name)
    Thread(target=client_send_msg, args=(header, pc_port)).start()


# Receive related information message from other end
def server_recv_msg(total_msg, rec_socket):
    global op_code
    global mtime
    global size
    global name
    global scan_dict
    global known_dict
    global known_size
    global buffer_size
    while True:
        connect_Socket, addr = rec_socket.accept()
        # "1" ,"8" and "6" means preparing receiving a file or folder bytes stream
        if (op_code == 1 or op_code == 6 or op_code == 8):
            # "1" means receive a file
            # "8" means receive modified file
            if (op_code == 1 or op_code==8):
                recv_file(name, connect_Socket,mtime)
            if (op_code == 6):
                receive_folder(name, connect_Socket,mtime)  # "6" means preparing receiving a folder
            connect_Socket.close()
            """
            After receiving bytes stream, record related file information in own dictionaries, which means 
            "this file has been synchronized"
            """
            known_dict[name] = os.path.getmtime(os.path.join("share", name))
            known_size[name] = os.path.getsize(os.path.join("share", name))
            op_code = 10
            continue
        """
         "0" and "10" means receiving message of file header information
        "3" means waiting for the message of receiving successfully
        """
        if (op_code == 0 or op_code == 10 or op_code == 3):
            content = connect_Socket.recv(buffer_size)
            total_msg = b''
            while len(content) > 0:  # Loop receiving message
               total_msg += content
               content = connect_Socket.recv(buffer_size)
            op_code, mtime, size, name = parse_header(total_msg)
            print("receive", op_code, mtime, size, name, 'from', addr[0])

            # After receiving, take responding operations according to current op_code
            """
            '3' means receiving the message of receiving successfully and 
             notify this end to record file modified time into known_dict and file size into known_size 
            """
            if (op_code == 3):
                known_dict[name] = os.path.getmtime(os.path.join("share", name))
                known_size[name] = os.path.getsize(os.path.join("share", name))
                op_code=10
            """
            '2' means requesting for the specific file
            After sending, the op_code should be "0" to receive next information state message 
            """
            if (op_code == 2):
                send_file(os.path.join("share", name), pc_port)
                op_code = 0
            """
            '7' means requesting for the specific folder
            After sending, the op_code should be "0" to receive next information state message
            """
            if (op_code == 7):
                send_folder(name, pc_port)
                op_code = 0
            """
            '8' means the file is modified, receive it anyway
            """
            if (op_code == 8):
                header = make_header(2, mtime, size, name)
                client_send_msg(header, pc_port)
            """ 
            '1' and '6' means checking whether one file or one folder has been synchronized or not
            '1' for files and '6' for folders
            """
            if (op_code == 1 or op_code == 6):
                # if this file hasn't been synchronized yet according to following checking, send requesting messages
                if (op_code == 1):
                    header = make_header(2, mtime, size, name)  # send "request file" message
                    client_send_msg(header, pc_port)
                if (op_code == 6):
                    header = make_header(7, mtime, size, name)  # send 'request folder' message
                    client_send_msg(header, pc_port)

# ================================================================
# start scan itself and exchange different files in both sides
def file_sychronization():
    global op_code
    global mtime
    global size
    global name
    global scan_dict
    global known_dict
    global known_size

    while True:
        try:
            time.sleep(0.5)
            scan_dict = scan_folder()  # scan "share" folder
            for f_name in scan_dict.keys():
                if (op_code == 10):  # scanning signal
                    # if this file has been synchronized
                    if f_name in known_dict.keys() and os.path.getsize(os.path.join("share", f_name)) == known_size[f_name]:
                        # if the file is modified
                        if os.path.getmtime(os.path.join("share", f_name)) != known_dict[f_name]:
                            # tell other side to receive modified file
                            header = make_header(8, os.path.getmtime(os.path.join("share", f_name)),
                                                 os.path.getsize(os.path.join("share", f_name)), f_name)
                            client_send_msg(header, pc_port)
                            op_code = 0  # waiting for receive message and stop scanning itself
                        else:
                            continue
                    else:
                        # if the file hasn't been synchronized and it is a file
                        if (os.path.isfile(os.path.join("share", f_name))):
                            # send 'applying for sending file' message
                            header = make_header(1, os.path.getmtime(os.path.join("share", f_name)),
                                                 os.path.getsize(os.path.join("share", f_name)), f_name)
                        else:
                            # send 'applying for sending folder' message to other side
                            header = make_header(6, os.path.getmtime(os.path.join("share", f_name)),
                                                 os.path.getsize(os.path.join("share", f_name)), f_name)
                        client_send_msg(header, pc_port)  # send corresponding information to other side
                        op_code = 0  # waiting for receive message and stop scanning itself

        # if the other side cannot be connected, handle this exception below
        except ConnectionRefusedError:
            print("Connection fail!")


def main():
    # start a new thread to receive messages
    pkg_thread = Thread(target=server_recv_msg, args=(b'', server_socket))
    pkg_thread.start()

    # In main thread
    creat_folder()
    file_sychronization()  # start to scan and exchange files in both ends


if __name__ == '__main__':
    main()


