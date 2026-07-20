variable "region" {

  description = "AWS Region"

  type = string
}



variable "my_ip" {

  description = "Your public IP without"

  type = string
}



variable "key_name" {

  description = "Existing EC2 Key Pair"

  type = string
}



variable "instance_type" {

  description = "EC2 instance type"

  type = string

  default = "t2.micro"
}
