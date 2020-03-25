#define _GNU_SOURCE
#include <sched.h>
#include <unistd.h>
#include <stdlib.h>
#include <stdio.h>
#include <sys/mount.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <string.h>
#include <fcntl.h>
#include <stdint.h>




int cpid = 0;

void sig_handler(int sig){
        printf("Received signal %d sending to child...\n", sig);
        kill(cpid,sig);
}




int main(int argc, char* argv[]){

        int flags = 0;
        int pid = 0;

        int cmd_len;
        int netns_len;
        int upid_len;

        char* cmd;
        char* net_ns;
        char* upid_file;

        int net_fd;
        int upid;
        int upid_fd;


        if (argc >=4) {

                cmd_len = strlen(argv[3]);
                netns_len = strlen(argv[1]);
                upid_len = strlen(argv[2]);

                cmd = (char*) calloc(cmd_len,sizeof(char));
                net_ns = (char*) calloc(netns_len,sizeof(char));
                upid_file = (char*) calloc(upid_len,sizeof(char));


                strncpy(cmd,argv[3], cmd_len);
                strncpy(net_ns,argv[1], netns_len);
                strncpy(upid_file,argv[2], upid_len);

                // flags = CLONE_NEWPID | CLONE_NEWNS | CLONE_NEWIPC | CLONE_SYSVSEM | CLONE_NEWUTS | CLONE_NEWUSER;
                flags = CLONE_NEWPID | CLONE_NEWNS | CLONE_NEWIPC | CLONE_SYSVSEM | CLONE_NEWUTS;

                printf("NET_NS: %s CMD: %s\n", net_ns, cmd);


                if (unshare(flags)==-1){
                        perror("Unshare:");
                        exit(-1);
                }


                pid = fork();
                if (pid==0){
                        //this is the child, mount and execvp here
                        char buf[255];

                        // storing the child PID
                        upid = getpid();
                        upid_fd = open(upid_file, O_WRONLY | O_CREAT);
                        if (upid_fd == -1) {
                                perror("PID file cannot be opened");
                                exit(-1);
                        }
                        sprintf(buf, "%d", upid);
                        write(upid_fd, buf, strlen(buf));
                        close(upid_fd);

                        // printf("Mapping root user\n");
                        // //mapping root user
                        // map_id(_PATH_PROC_UIDMAP, 0, real_euid);
                        // map_id(_PATH_PROC_GIDMAP, 0, real_egid);



                        //opening network namespace file
                        net_fd = open(net_ns, O_RDONLY);
                        if (net_fd == -1){
                                perror("open net ns file");
                                exit(-1);
                        }


                        //moving to network namespace
                        if(setns(net_fd,CLONE_NEWNET) ==-1){
                                perror("Cannot setns");
                                exit(-1);
                        }
                        close(net_fd);
                        free(net_ns);

                        //chrooting
                        /*
                        if(chroot(rootfs)){
                                perror("Cannot chroot");
                                exit(-1);
                        }
                        free(rootfs);
                        */

                        //mounting proc
                        if(mount("none","/proc","proc", MS_NOSUID|MS_NOEXEC|MS_NODEV, NULL) != 0){
                                perror("Cannot mount proc");
                                exit(-1);
                        }

                        /*
                        //mounting sys
                        if(mount("none","/sys","sysfs", 0, NULL) != 0){
                                perror("Cannot mount sys");
                                exit(-1);
                        }
                        //mounting tmp
                        if(mount("none","/tmp","tmpfs", 0, NULL) != 0){
                                perror("Cannot mount tmp");
                                exit(-1);
                        }
                        */

                        //executing command

                        execvp(cmd,&argv[3]);


                }else{
                        cpid = pid;
                        signal(SIGINT, sig_handler);
                        //this is the parent, wait the child here
                        //free(rootfs);
                        free(net_ns);
                        free(cmd);
                        int ret=0;
                        waitpid(pid,&ret,0);
                }

        }else{
                printf("[Usage] %s <network namespace> <cmd> [command arguments]\n", argv[0]);
        }


}