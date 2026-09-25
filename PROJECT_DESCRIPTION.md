Computer Networks Mini Project
Designing a Proxy Server
Project Overview

The project is to design and implement a forward proxy server that acts as an intermediary between a client and a destination web server. The proxy will receive requests from clients, process and inspect the requests, and forward allowed requests to the intended destination server. It will then receive the response from the destination server and send it back to the client.

The proxy will primarily handle HTTP requests using TCP sockets.

Main Objectives

The main objectives of the project are:

Understand the working and structure of HTTP requests and responses.
Understand the difference between forward and reverse proxies.
Implement a forward proxy that can receive and forward HTTP requests.
Handle multiple clients simultaneously.
Implement caching to avoid repeatedly fetching the same resources.
Implement an access-control feature to block selected domains or URLs.
Maintain useful logs of proxy activity.
Handle malformed requests and unreachable destination servers gracefully.
Measure the performance overhead introduced by the proxy compared with a direct connection.
Planned Architecture

The basic communication flow will be:

Client → Forward Proxy → Destination Server

The proxy will perform the following steps:

Accept a client connection.
Receive the HTTP request.
Parse the request.
Check access-control rules.
Check whether the requested resource is available in the cache.
If there is a valid cache entry, return the cached response.
If there is no valid cache entry, connect to the destination server.
Forward the client's request.
Receive the destination server's response.
Store suitable responses in the cache.
Send the response back to the client.
Record the request and result in the log.
Technologies
Programming Language: Python
Protocol: HTTP
Transport Protocol: TCP
Networking: Python socket programming
Concurrency: Thread-based client handling
Caching: File-based cache
Access Control: Domain/URL blocking
Logging: File-based logging
Version Control: Git and GitHub
