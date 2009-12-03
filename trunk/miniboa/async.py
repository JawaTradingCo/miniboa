# -*- coding: utf-8 -*-
#------------------------------------------------------------------------------
#   miniboa/async.py
#   Copyright 2009 Jim Storch
#   Licensed under the Apache License, Version 2.0 (the "License"); you may
#   not use this file except in compliance with the License. You may obtain a
#   copy of the License at http://www.apache.org/licenses/LICENSE-2.0
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#   License for the specific language governing permissions and limitations
#   under the License.
#------------------------------------------------------------------------------

"""Handle Asynchronous Telnet Connections."""

import socket
import select
import time
import sys

from miniboa.telnet import Telnet
from miniboa import BogConnectionLost

## Cap sockets to 512 on Windows because winsock can only process 512 at time
if sys.platform == 'win32':
    MAX_CONNECTIONS = 512
## Cap sockets to 1000 on Linux because you can only have 1024 file descriptors
else:
    MAX_CONNECTIONS = 1000


#-----------------------------------------------------Dummy Connection Handlers

def _on_connect(client):
    """Placeholder new connection handler."""
    print "++ Opened connection to %s, sending greeting..." % client.addrport()
    client.send("Greetings from Miniboa! "
        " Now it's time to add your code.\r\n")

def _on_disconnect(client):
    """Placeholder lost connection handler."""
    print "-- Lost connection to %s" % client.addrport()


#-----------------------------------------------------------------Telnet Server

class TelnetServer(object):

    """
    Poll sockets for new connections and sending/receiving data from clients.
    """

    def __init__(self, port=7777, address='', on_connect=_on_connect,
            on_disconnect=_on_disconnect):
        """
        Create a new Telnet Server.

        port -- Port to listen for new connection on.  On UNIX-like platforms,
            you made need root access to use ports under 1025.

        address -- Address of the LOCAL network interface to listen on.  You
            can usually leave this blank unless you want to restrict traffic
            to a specific network device.  This will usually NOT be the same
            as the Internet address of your server.

        on_connect -- function to call with new telnet connections

        on_disconnect -- function to call when a client's connection dies,
            either through a terminated session or client.active being set
            to False.
        """

        ## Socket Setup
        self.port = port
        self.address = address

#        ## Connection Handlers
#        if on_connect == None:
#            self.on_connect = on_connect
#        else:
#            self.on_connect = self._on_connect

#        if on_disconnect != None:
#            self.on_disconnect = on_disconnect
#        else:
#            self.on_disconnect = self._on_disconnect

        ## Function to call with new Telnet sessions
        self.on_connect = on_connect
        ## Function to call when existing connections are lost
        self.on_disconnect = on_disconnect

        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server_socket.bind((address, port))
            server_socket.listen(5)
        except socket.error, e:
            print >>sys.stderr, "Unable to create the server socket:", e
            sys.exit(1)

        self.server_socket = server_socket
        self.server_fd = server_socket.fileno()

        ## Dictionary of active connections,
        ## key = file descriptor, value = Telnet Clients (see miniboa.telnet)
        self.connections = {}

    def connection_count(self):

        """
        Returns the number of active connections.
        """

        return len(self.connections)

    def poll(self):

        """
        Perform a non-blocking scan of recv and send states on the server
        and client connection sockets.  Process new connection requests,
        read incomming data, and send outgoing data.  Sends and receives may
        be partial.
        """

        ## Build a list of connections to test for receive data pending
        recv_list = [self.server_fd]    # always add the server
        for client in self.connections.values():
            if client.active:
                recv_list.append(client.fileno)
            ## Delete inactive connections from the dictionary
            else:
                #print "-- Lost connection to %s" % client.addrport()
                self.on_disconnect(client)
                del self.connections[client.fileno]

        ## Build a list of connections that need to send data
        send_list = []
        for client in self.connections.values():
            if client.send_pending:
                send_list.append(client.fileno)

        ## Get active socket file descriptors from select.select()
        try:
            rlist, slist, elist = select.select(recv_list, send_list, [], 0)

        except select.error, err:
            ## If we can't even use select(), game over man, game over
            print >>sys.stderr, ("!! FATAL SELECT error '%d:%s'!"
                % (err[0], err[1]))
            sys.exit(1)

        ## Process socket file descriptors with data to recieve
        for sockfd in rlist:

            ## If it's coming from the server's socket then this is a new
            ## connection request.
            if sockfd == self.server_fd:

                try:
                    sock, addr_tup = self.server_socket.accept()

                except socket.error, err:
                    print >>sys.stderr, ("!! ACCEPT error '%d:%s'." %
                        (err[0], err[1]))
                    continue

                ## Check for maximum connections
                if self.connection_count() >= ( MAX_CONNECTIONS ):
                    print '?? Refusing new connection; maximum in use.'
                    sock.close()
                    continue

                client = Telnet(sock, addr_tup)
                #print "++ Opened connection to %s" % client.addrport()
                ## Add the connection to our dictionary
                self.connections[client.fileno] = client

                ## Whatever we do with new connections goes here:
                self.on_connect(client)

            else:
                ## Call the connection's recieve method
                try:
                    self.connections[sockfd].socket_recv()
                except BogConnectionLost, ex:
                    #print ex, 'BCE!'
                    client.active = False

        ## Process sockets with data to send
        for sockfd in slist:
            ## Call the connection's send method
            self.connections[sockfd].socket_send()
